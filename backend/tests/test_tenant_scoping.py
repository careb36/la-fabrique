"""Every table carries the company it belongs to, or says why it does not.

Tenant scoping is expensive to retrofit. This test keeps it
from wearing away: a new table without ``company_id`` fails here until it is
scoped or listed below with its reason. (From block/buzz, whose migration
tests require ``community_id`` on every table outside a reasoned list.)
"""

import models  # noqa: F401 - registers every table on the metadata
from sqlmodel import SQLModel

# Tables that hold no company's data, or reach their company through a parent.
GLOBAL_TABLES = {
    "companies": "the tenant itself",
    "users": "a person can belong to several companies, through company_members",
    "bug_reports": "help-desk tickets are not company data: a support admin sees all of them",
    "outbox_events": "a transport queue; each event's payload names its sprint and company",
    "backlog_items": "scoped through sprint_id, whose sprint carries company_id",
}

# Tables whose company_id may be empty, and why.
NULLABLE_COMPANY = {
    "audit_log": "rows written before company scoping, flagged as legacy and never shown under a company",
}


def _tables():
    return SQLModel.metadata.tables


def test_every_table_carries_company_id_or_says_why_not():
    missing = sorted(
        name
        for name, table in _tables().items()
        if "company_id" not in table.c and name not in GLOBAL_TABLES
    )
    assert missing == [], (
        f"tables without company_id and without a reason in GLOBAL_TABLES: {missing}"
    )


def test_company_id_points_at_companies_and_is_required():
    problems = []
    for name, table in _tables().items():
        column = table.c.get("company_id")
        if column is None:
            continue
        targets = {fk.target_fullname for fk in column.foreign_keys}
        if targets != {"companies.id"}:
            problems.append(f"{name}.company_id references {targets or 'nothing'}")
        if column.nullable and name not in NULLABLE_COMPANY:
            problems.append(f"{name}.company_id is nullable")
    assert problems == []


def test_a_table_reached_through_a_parent_keeps_that_link_required():
    sprint_id = _tables()["backlog_items"].c["sprint_id"]
    assert {fk.target_fullname for fk in sprint_id.foreign_keys} == {"sprints.id"}
    assert sprint_id.nullable is False


def test_the_lists_name_only_tables_that_exist_and_need_them():
    tables = _tables()
    stale = [
        name
        for name in GLOBAL_TABLES
        if name not in tables or "company_id" in tables[name].c
    ]
    stale += [
        name
        for name in NULLABLE_COMPANY
        if name not in tables or not tables[name].c["company_id"].nullable
    ]
    assert stale == []
