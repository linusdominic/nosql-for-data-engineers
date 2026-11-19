"""Deterministic synthetic data for Larkspur Lending, a fictional consumer lender.

Everything here is invented: the lender, every borrower name, employer, street, town,
phone number, email address and amount. Phone numbers use the +999 prefix, which is not
assigned to any country, and emails use example.com, a domain reserved for documentation.

The generator is seeded, so `generate(seed=42)` returns the same world on every machine
and every run. That is what lets the guide quote exact row counts.

The world has three kinds of records:

* applications (MongoDB): one JSON-like document per loan application, with the
  borrower, contact details, decision, uploaded documents and, once funded, the loan
  embedded in it. `application_as_of(app, t)` returns the document as it looked at time t,
  which is how the capstone simulates a source system changing between pipeline runs.
* payment events (Cassandra): one event per instalment received, with the time it was
  paid (`event_time`) and the time it reached the lender's systems (`ingested_at`). A few
  arrive days late, on purpose.
* fraud rings (Neo4j ground truth): small groups of applications from different people
  that are chained together by a shared phone, device or address.
"""

from __future__ import annotations

import copy
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

LENDER_NAME = "Larkspur Lending (fictional)"

FIRST_NAMES = [
    "Ada", "Bram", "Cleo", "Dov", "Elin", "Faris", "Greta", "Hugo", "Ines", "Jory",
    "Kalla", "Lio", "Mira", "Nils", "Odile", "Pim", "Quinn", "Rosa", "Sami", "Tova",
    "Ulla", "Vito", "Wren", "Xena", "Yusuf", "Zora", "Arlo", "Bea", "Cyrus", "Dalia",
    "Emre", "Fen", "Gil", "Hana", "Ivo", "Juno", "Kit", "Lark", "Moss", "Nova",
]  # fmt: skip
SURNAMES = [
    "Ashcombe", "Brindlemoor", "Cattermole", "Duskwell", "Elderfield", "Fallowby",
    "Greythorne", "Hollinsby", "Ivesdale", "Juniper", "Kettlewick", "Larkholme",
    "Marrowby", "Netherwood", "Oakhanger", "Pellbrook", "Quillon", "Rookwell",
    "Saltmarsh", "Thistlecombe", "Underhay", "Vantwick", "Wrenfold", "Yarrowby",
]  # fmt: skip
TOWNS = [
    ("Port Merrow", "ZZ1"), ("Eastbridge Vale", "ZZ2"), ("Holloway Cross", "ZZ3"),
    ("Fernmouth", "ZZ4"), ("Kestrel Bay", "ZZ5"), ("Ashby Fen", "ZZ6"),
    ("Lowmarsh", "ZZ7"), ("Cindervale", "ZZ8"),
]  # fmt: skip
STREETS = [
    "Lantern Row", "Quarry Lane", "Thistle Way", "Copper Street", "Mill Race",
    "Heron Walk", "Orchard Close", "Saltpan Road", "Bellfounder Yard", "Rope Walk",
]  # fmt: skip
EMPLOYERS = [
    "Quillfeather Joinery (fictional)", "Brightwater Logistics (fictional)",
    "Old Forge Bakery (fictional)", "Kestrel Bay Council (fictional)",
    "Northlight Clinics (fictional)", "Tidewater Freight (fictional)",
]  # fmt: skip
EMPLOYMENT_STATUSES = ["employed", "employed", "employed", "self_employed", "retired"]
CHANNELS = ["web", "web", "mobile", "mobile", "broker", "branch"]
DOC_TYPES = ["id_proof", "payslip", "bank_statement", "utility_bill"]
DECLINE_REASONS = [
    "high_debt_to_income", "thin_credit_file", "affordability", "policy_rule",
    "identity_unverified",
]  # fmt: skip
PAYMENT_METHODS = ["direct_debit", "direct_debit", "direct_debit", "card", "bank_transfer"]

# product -> (min amount, max amount, allowed terms in months, base annual rate)
PRODUCTS: dict[str, tuple[int, int, list[int], float]] = {
    "personal": (2_000, 25_000, [12, 24, 36, 48, 60], 0.11),
    "auto": (5_000, 40_000, [24, 36, 48, 60], 0.08),
    "home_improvement": (5_000, 60_000, [36, 60, 84, 120], 0.075),
}

# Dates where the source system changed shape. Chapter 2 and the capstone handle these.
DRIFT_AMOUNT_AS_STRING_FROM = datetime(2025, 4, 1, tzinfo=UTC)  # broker feed sends strings
DRIFT_NEW_FIELD_FROM = datetime(2025, 5, 1, tzinfo=UTC)  # marketing_consent appears


@dataclass
class World:
    """Everything the generator produced, plus the ground truth used by the checks."""

    seed: int
    as_of: datetime
    borrowers: list[dict[str, Any]]
    applications: list[dict[str, Any]]
    payments: list[dict[str, Any]]
    rings: list[list[str]] = field(default_factory=list)
    households: list[list[str]] = field(default_factory=list)


def _dt(d: date, seconds: int = 0) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=UTC) + timedelta(seconds=seconds)


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(d.day, 28))


def instalment_amount(principal: float, annual_rate: float, term_months: int) -> float:
    """Monthly payment of a fully amortising loan (the usual annuity formula)."""
    r = annual_rate / 12
    if r == 0:
        return round(principal / term_months, 2)
    return round(principal * r / (1 - (1 + r) ** -term_months), 2)


def _unique(rng: random.Random, seen: set[str], make: Any) -> str:
    while True:
        value: str = make(rng)
        if value not in seen:
            seen.add(value)
            return value


def generate(
    seed: int = 42,
    n_borrowers: int = 2_000,
    applications_from: date = date(2025, 1, 1),
    applications_to: date = date(2025, 6, 30),
    as_of: date = date(2025, 12, 31),
    ring_count: int = 8,
) -> World:
    """Generate a complete, reproducible world. Same arguments, same output."""
    rng = random.Random(seed)
    as_of_dt = _dt(as_of, 86_399)
    phones: set[str] = set()
    devices: set[str] = set()
    addresses: set[str] = set()

    def new_phone(r: random.Random) -> str:
        return f"+999 7{r.randint(0, 99_999_999):08d}"

    def new_device(r: random.Random) -> str:
        return f"dev-{r.getrandbits(48):012x}"

    def new_address(r: random.Random) -> str:
        return f"{r.randint(1, 240)} {r.choice(STREETS)}|{r.randrange(len(TOWNS))}"

    borrowers: list[dict[str, Any]] = []
    for i in range(1, n_borrowers + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(SURNAMES)
        line1, town_idx = _unique(rng, addresses, new_address).split("|")
        town, prefix = TOWNS[int(town_idx)]
        status = rng.choice(EMPLOYMENT_STATUSES)
        borrowers.append(
            {
                "borrower_id": f"B{i:06d}",
                "full_name": f"{first} {last}",
                "date_of_birth": date(
                    rng.randint(1955, 2004), rng.randint(1, 12), rng.randint(1, 28)
                ).isoformat(),
                "email": f"{first.lower()}.{last.lower()}{i}@example.com",
                "phone": _unique(rng, phones, new_phone),
                "address": {"line1": line1, "town": town, "postcode": f"{prefix} {i % 9}AB"},
                "annual_income": rng.randrange(18_000, 160_000, 500),
                "employment": {
                    "status": status,
                    "employer": None if status == "retired" else rng.choice(EMPLOYERS),
                    "years": rng.randint(0, 30),
                },
                "device_id": _unique(rng, devices, new_device),
            }
        )

    # Households: a few pairs of borrowers who genuinely live together. They share an
    # address, which is a link in the graph but not fraud. Chapter 6 shows why a rule
    # like "two applications share an address" needs a threshold.
    households: list[list[str]] = []
    pool = list(range(len(borrowers)))
    rng.shuffle(pool)
    for k in range(0, int(n_borrowers * 0.03) * 2, 2):
        a, b = borrowers[pool[k]], borrowers[pool[k + 1]]
        b["address"] = copy.deepcopy(a["address"])
        households.append([a["borrower_id"], b["borrower_id"]])

    span_seconds = int((_dt(applications_to, 86_399) - _dt(applications_from)).total_seconds())
    applications: list[dict[str, Any]] = []
    for b in borrowers:
        n_apps = 2 if rng.random() < 0.2 else 1
        for _ in range(n_apps):
            applications.append(_make_application(rng, b, applications_from, span_seconds))
    applications.sort(key=lambda a: (a["submitted_at"], a["application_id"]))
    for n, app in enumerate(applications, start=1):
        app["application_id"] = f"A{n:07d}"
        app["_id"] = app["application_id"]
        if app.get("loan"):
            app["loan"]["loan_id"] = f"L{n:07d}"

    rings = _plant_rings(rng, applications, ring_count, phones, devices, addresses)
    ring_apps = {a for ring in rings for a in ring}

    payments: list[dict[str, Any]] = []
    for app in applications:
        loan = app.get("loan")
        if loan is None:
            continue
        payments.extend(_payments_for_loan(rng, loan, as_of_dt, app["application_id"] in ring_apps))
    payments.sort(key=lambda p: (p["event_time"], p["event_id"]))

    return World(
        seed=seed,
        as_of=as_of_dt,
        borrowers=borrowers,
        applications=applications,
        payments=payments,
        rings=rings,
        households=households,
    )


def _make_application(
    rng: random.Random, b: dict[str, Any], start: date, span_seconds: int
) -> dict[str, Any]:
    submitted_at = _dt(start, rng.randrange(span_seconds))
    product = rng.choice(list(PRODUCTS))
    lo, hi, terms, base_rate = PRODUCTS[product]
    amount = float(rng.randrange(lo, hi, 250))
    term = rng.choice(terms)
    channel = rng.choice(CHANNELS)
    score = max(300, min(850, int(rng.gauss(660, 80))))
    decided_at = submitted_at + timedelta(seconds=rng.randint(3_600, 7 * 86_400))

    reasons: list[str] = []
    if rng.random() < 0.05:
        outcome = "withdrawn"
    elif score >= 620:
        outcome = "approved"
    else:
        outcome, reasons = "declined", rng.sample(DECLINE_REASONS, rng.randint(1, 2))

    docs = [
        {
            "doc_type": t,
            "uploaded_at": submitted_at + timedelta(minutes=rng.randint(0, 600)),
            "verified": rng.random() < 0.9,
        }
        for t in rng.sample(DOC_TYPES, rng.randint(1, 4))
    ]
    borrower: dict[str, Any] = {
        "borrower_id": b["borrower_id"],
        "full_name": b["full_name"],
        "date_of_birth": b["date_of_birth"],
        "annual_income": b["annual_income"],
        "employment": copy.deepcopy(b["employment"]),
    }
    if rng.random() < 0.05:
        del borrower["employment"]  # drift: some front ends never sent it

    app: dict[str, Any] = {
        "application_id": "",
        "borrower": borrower,
        "contact": {"email": b["email"], "phone": b["phone"]},
        "address": copy.deepcopy(b["address"]),
        "device_id": b["device_id"],
        "product": product,
        "requested_amount": amount,
        "term_months": term,
        "channel": channel,
        "submitted_at": submitted_at,
        "documents": docs,
        "schema_version": 1,
        # Not stored in the database. Used by application_as_of().
        "_final_status": outcome,
        "_decision": {
            "score": score,
            "outcome": outcome,
            "reasons": reasons,
            "decided_at": decided_at,
        },
    }
    if channel == "broker" and submitted_at >= DRIFT_AMOUNT_AS_STRING_FROM:
        app["requested_amount"] = f"{amount:.2f}"  # drift: a type change
        app["schema_version"] = 2
    if submitted_at >= DRIFT_NEW_FIELD_FROM:
        app["marketing_consent"] = rng.random() < 0.6  # drift: a new field
    if outcome == "approved" and rng.random() < 0.92:
        rate = round(base_rate + (850 - score) / 4_000 + rng.uniform(-0.005, 0.005), 4)
        app["loan"] = {
            "loan_id": "",
            "principal": amount,
            "annual_rate": rate,
            "term_months": term,
            "instalment": instalment_amount(amount, rate, term),
            "originated_at": decided_at + timedelta(days=rng.randint(1, 5)),
        }
    return app


def _plant_rings(
    rng: random.Random,
    applications: list[dict[str, Any]],
    ring_count: int,
    phones: set[str],
    devices: set[str],
    addresses: set[str],
) -> list[list[str]]:
    """Chain small groups of applications from different borrowers together.

    In a ring of members m0..mk, m0 and m1 share a phone, m1 and m2 share a device,
    m2 and m3 share an address, and so on. No single identifier links the whole ring,
    so only a multi-hop traversal finds it.
    """
    rings: list[list[str]] = []
    used_borrowers: set[str] = set()
    candidates = [a for a in applications if a["_final_status"] == "approved" and a.get("loan")]
    rng.shuffle(candidates)
    kinds = ["phone", "device", "address"]
    cursor = 0
    for _ in range(ring_count):
        size = rng.randint(3, 6)
        members: list[dict[str, Any]] = []
        while len(members) < size and cursor < len(candidates):
            app = candidates[cursor]
            cursor += 1
            if app["borrower"]["borrower_id"] in used_borrowers:
                continue
            used_borrowers.add(app["borrower"]["borrower_id"])
            members.append(app)
        for j in range(len(members) - 1):
            kind = kinds[j % 3]
            left, right = members[j], members[j + 1]
            if kind == "phone":
                value = f"+999 7{rng.randint(0, 99_999_999):08d}"
                while value in phones:
                    value = f"+999 7{rng.randint(0, 99_999_999):08d}"
                phones.add(value)
                left["contact"]["phone"] = right["contact"]["phone"] = value
            elif kind == "device":
                value = f"dev-{rng.getrandbits(48):012x}"
                devices.add(value)
                left["device_id"] = right["device_id"] = value
            else:
                town, prefix = TOWNS[rng.randrange(len(TOWNS))]
                line1 = f"Flat {rng.randint(1, 40)}, {rng.randint(1, 240)} {rng.choice(STREETS)}"
                addresses.add(line1)
                shared = {"line1": line1, "town": town, "postcode": f"{prefix} 9ZZ"}
                left["address"] = copy.deepcopy(shared)
                right["address"] = copy.deepcopy(shared)
        rings.append(sorted(m["application_id"] for m in members))
    return rings


def _payments_for_loan(
    rng: random.Random, loan: dict[str, Any], as_of: datetime, in_ring: bool
) -> list[dict[str, Any]]:
    """One event per instalment received. Some borrowers pay late, some stop paying."""
    originated = loan["originated_at"].date()
    behaviour = rng.random()
    stop_at: int | None = None
    if in_ring:
        stop_at = rng.randint(1, 3)  # first-payment default is a classic fraud signal
    elif behaviour < 0.08:
        stop_at = rng.randint(2, 9)
    late_payer = 0.08 <= behaviour < 0.20
    events: list[dict[str, Any]] = []
    for n in range(1, loan["term_months"] + 1):
        due = _add_months(originated, n)
        if _dt(due) > as_of:
            break
        if stop_at is not None and n >= stop_at:
            break
        days_late = rng.randint(5, 25) if late_payer and rng.random() < 0.5 else rng.randint(-3, 2)
        paid_at = _dt(due, rng.randrange(86_400)) + timedelta(days=days_late)
        if paid_at > as_of:
            break
        delay = (
            timedelta(days=rng.randint(1, 3))
            if rng.random() < 0.03
            else timedelta(seconds=rng.randint(1, 900))
        )
        events.append(
            {
                "event_id": _uuid(rng),
                "loan_id": loan["loan_id"],
                "instalment_no": n,
                "due_date": due,
                "event_time": paid_at,
                "event_day": paid_at.date(),
                "ingested_at": paid_at + delay,
                "amount_cents": round(loan["instalment"] * 100),
                "method": rng.choice(PAYMENT_METHODS),
            }
        )
    return events


def application_as_of(app: dict[str, Any], t: datetime) -> dict[str, Any] | None:
    """The application document as the source system held it at time `t`.

    Returns None if it had not been submitted yet. Status moves
    submitted -> approved/declined/withdrawn -> funded, and `updated_at` is the time of
    the latest change, which is what an incremental extract keys on.
    """
    if t < app["submitted_at"]:
        return None
    doc: dict[str, Any] = {"_id": app["_id"]}
    doc.update({k: copy.deepcopy(v) for k, v in app.items() if not k.startswith("_")})
    decision = app["_decision"]
    loan = doc.pop("loan", None)
    if t < decision["decided_at"]:
        doc["status"] = "submitted"
        doc["updated_at"] = app["submitted_at"]
        return doc
    doc["decision"] = copy.deepcopy(decision)
    doc["status"] = decision["outcome"]
    doc["updated_at"] = decision["decided_at"]
    if loan is not None and t >= loan["originated_at"]:
        doc["loan"] = loan
        doc["status"] = "funded"
        doc["updated_at"] = loan["originated_at"]
    return doc


def applications_as_of(world: World, t: datetime) -> list[dict[str, Any]]:
    """Every application that existed at time `t`, in its state at that time."""
    out = []
    for app in world.applications:
        doc = application_as_of(app, t)
        if doc is not None:
            out.append(doc)
    return out


def payments_ingested_by(world: World, t: datetime) -> list[dict[str, Any]]:
    """Payment events that had reached the lender's systems by time `t`."""
    return [p for p in world.payments if p["ingested_at"] <= t]


def summary(world: World) -> dict[str, int]:
    """Row counts, used by `nosqlde datagen` and quoted in the guide."""
    final = applications_as_of(world, world.as_of)
    return {
        "borrowers": len(world.borrowers),
        "applications": len(final),
        "funded_loans": sum(1 for a in final if a["status"] == "funded"),
        "payment_events": len(world.payments),
        "late_arriving_events": sum(
            1 for p in world.payments if p["ingested_at"] - p["event_time"] > timedelta(hours=1)
        ),
        "fraud_rings": len(world.rings),
        "ring_applications": sum(len(r) for r in world.rings),
        "households": len(world.households),
        "amount_as_string_docs": sum(1 for a in final if isinstance(a["requested_amount"], str)),
        "missing_employment_docs": sum(1 for a in final if "employment" not in a["borrower"]),
    }
