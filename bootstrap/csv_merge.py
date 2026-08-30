"""Merge a segment CSV into a drafted company summary."""

import csv
import io
import re

REQUIRED_COLUMNS = ("segment", "customers", "monthly_churn")


class CsvMergeError(ValueError):
    """Raised when a CSV row cannot be applied. The message lists every problem."""


def merge_csv(company, csv_text):
    """Update matching segments in place and return unmatched rows.

    Matching is by segment id (case-insensitive) across every plan.
    Unmatched rows are returned for the user to assign or discard.
    Malformed rows abort the merge with CsvMergeError; company is unchanged.
    """
    if not isinstance(company, dict):
        raise TypeError("company must be an object")
    if not isinstance(csv_text, str):
        raise TypeError("csv_text must be a string")

    rows, problems = _parse_rows(csv_text)
    if problems:
        raise CsvMergeError(_loud_problems(problems))

    index = _segment_index(company)
    unmatched = []
    updates = []
    for row in rows:
        key = row["segment"].lower()
        targets = index.get(key)
        if not targets:
            unmatched.append(
                {
                    "segment": row["segment"],
                    "customers": row["customers"],
                    "monthly_churn": row["monthly_churn"],
                }
            )
            continue
        updates.append((targets, row))

    for targets, row in updates:
        for segment in targets:
            segment["customers"] = row["customers"]
            segment["monthly_churn"] = row["monthly_churn"]
    return unmatched


def _parse_rows(csv_text):
    problems = []
    if not csv_text.strip():
        problems.append("the CSV is empty")
        return [], problems

    handle = io.StringIO(csv_text)
    try:
        reader = csv.DictReader(handle)
    except csv.Error as exc:
        problems.append("the CSV could not be read: %s" % exc)
        return [], problems

    if not reader.fieldnames:
        problems.append("the CSV has no header row")
        return [], problems

    header_map = {}
    for name in reader.fieldnames:
        if name is None:
            continue
        key = _norm_header(name)
        if key:
            header_map[key] = name
    missing = [column for column in REQUIRED_COLUMNS if column not in header_map]
    if missing:
        problems.append(
            "CSV must have columns segment, customers, monthly_churn (missing: %s)"
            % ", ".join(missing)
        )
        return [], problems

    rows = []
    for line_number, raw in enumerate(reader, start=2):
        if raw is None:
            problems.append("line %s is malformed" % line_number)
            continue
        if _row_blank(raw):
            continue
        if None in raw:
            problems.append(
                "line %s has more fields than the header"
                % line_number
            )
            continue
        segment = raw.get(header_map["segment"])
        customers_raw = raw.get(header_map["customers"])
        churn_raw = raw.get(header_map["monthly_churn"])
        segment_id = (segment or "").strip()
        if not segment_id:
            problems.append("line %s is missing a segment id" % line_number)
            continue
        customers, customers_error = _parse_customers(customers_raw)
        if customers_error:
            problems.append("line %s: %s" % (line_number, customers_error))
            continue
        churn, churn_error = _parse_churn(churn_raw)
        if churn_error:
            problems.append("line %s: %s" % (line_number, churn_error))
            continue
        rows.append(
            {
                "segment": segment_id,
                "customers": customers,
                "monthly_churn": churn,
            }
        )
    return rows, problems


def _loud_problems(problems):
    if len(problems) == 1:
        return "CSV rejected: %s" % problems[0]
    numbered = "; ".join(problems)
    return "CSV rejected (%s problems): %s" % (len(problems), numbered)


def _norm_header(name):
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _row_blank(raw):
    values = [value for value in raw.values() if value is not None]
    return not any(str(value).strip() for value in values)


def _parse_customers(raw):
    if raw is None or str(raw).strip() == "":
        return None, "customers is missing"
    text = str(raw).strip().replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None, "customers %r is not a number" % raw
    if number != number or number < 0:
        return None, "customers %r is not a valid count" % raw
    if number == int(number):
        return int(number), None
    return number, None


def _parse_churn(raw):
    if raw is None or str(raw).strip() == "":
        return None, "monthly_churn is missing"
    text = str(raw).strip()
    try:
        number = float(text)
    except ValueError:
        return None, "monthly_churn %r is not a number" % raw
    if number != number or number < 0 or number > 1:
        return None, "monthly_churn %r must be a fraction between 0 and 1" % raw
    return number, None


def _segment_index(company):
    index = {}
    for plan in company.get("plans") or []:
        for segment in plan.get("segments") or []:
            key = str(segment.get("id", "")).strip().lower()
            if not key:
                continue
            index.setdefault(key, []).append(segment)
    return index
