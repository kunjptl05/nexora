import re
from typing import Dict, List, Optional, Tuple

FIELD_ALIASES: Dict[str, List[str]] = {
    "candidate_name": ["candidate name", "applicant name", "student name", "full name", "name"],
    "father_name": ["father's name", "father name", "parent name"],
    "application_id": ["application id", "application number", "application no"],
    "record_id": ["candidate id", "student id", "id"],
    "date_of_birth": ["date of birth", "birth date", "dob"],
    "aadhaar_number": ["aadhaar card number", "aadhar card number", "aadhaar number", "aadhar number"],
    "email": ["email address", "e-mail", "email"],
    "mobile": ["mobile number", "mobile no", "phone number", "contact number", "mobile", "phone"],
    "bank_name": ["bank name"],
    "bank_branch": ["bank branch", "branch name"],
    "ifsc_code": ["ifsc code"],
    "bank_account": ["bank savings a/c no", "bank account number", "savings account number", "bank a/c no"],
    "ration_card_number": ["ration card number", "ration card no"],
    "bpl_card_number": ["bpl card number", "bpl card no"],
    "bpl_score": ["bpl score"],
    "board": ["board"],
    "stream": ["stream"],
    "percentage": ["percentage"],
    "percentile": ["percentile"],
    "tuition_fees": ["yearly tuition fees", "yearly tuition fee", "tuition fee"],
    "enrollment_number": ["enrollment number", "enrolment number", "enrollment no"],
    "seat_number": ["seat number", "seat no", "roll number", "roll no"],
    "university": ["university"],
    "institute": ["institute", "institution", "college"],
    "programme": ["programme", "program", "course"],
    "family_income": ["family annual income", "annual family income", "family income"],
    "category": ["category", "caste category"],
    "gender": ["gender"],
    "scholarship_year": ["scholarship year", "academic year"],
}

_LABEL_LOOKUP = {
    re.sub(r"[^a-z0-9]+", " ", label.lower()).strip(): (field_key, label)
    for field_key, labels in FIELD_ALIASES.items()
    for label in labels
}
_ALL_LABELS = sorted(
    (label for labels in FIELD_ALIASES.values() for label in labels),
    key=len,
    reverse=True
)
_LABEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<label>" + "|".join(re.escape(label) for label in _ALL_LABELS) + r")(?![A-Za-z0-9])\s*[:：]\s*",
    re.IGNORECASE
)

_FIELD_INTENTS = [
    ("application_id", re.compile(r"\bapplication\s*(?:id|number|no\.?)\b", re.I)),
    ("date_of_birth", re.compile(r"\b(date\s+of\s+birth|birth\s+date|dob)\b", re.I)),
    ("email", re.compile(r"\b(e-?mail(?:\s+address)?)\b", re.I)),
    ("mobile", re.compile(r"\b(mobile|phone|contact\s+number)\b", re.I)),
    ("father_name", re.compile(r"\b(father(?:'s)?|parent)\s+name\b", re.I)),
    ("gender", re.compile(r"\bgender\b", re.I)),
    ("category", re.compile(r"\b(category|caste)\b", re.I)),
    ("scholarship_year", re.compile(r"\b(scholarship|academic)\s+year\b", re.I)),
    ("enrollment_number", re.compile(r"\b(enrol?l?ment)\s+(?:number|no\.?)\b", re.I)),
    ("seat_number", re.compile(r"\b(seat|roll)\s+(?:number|no\.?)\b", re.I)),
    ("university", re.compile(r"\buniversity\b", re.I)),
    ("institute", re.compile(r"\b(institute|institution|college)\b", re.I)),
    ("programme", re.compile(r"\b(programme|program|course)\b", re.I)),
    ("family_income", re.compile(r"\b(family|annual)\s+income\b", re.I)),
]


def detect_field_intent(question: str) -> Optional[str]:
    text = question.lower()
    for field_key, pattern in _FIELD_INTENTS:
        if pattern.search(text):
            return field_key
    if re.search(r"\b(name|person|applicant|candidate|student)\b", text):
        if not re.search(r"\b(component|components|part|parts|chemistry|chemistries)\b", text):
            return "candidate_name"
    return None


def extract_labelled_fields(text: str) -> List[Dict[str, object]]:
    """Extract exact label:value pairs, including multiple fields on one PDF line."""
    results: List[Dict[str, object]] = []
    current_page = 1
    pending_field: Optional[Tuple[str, str]] = None

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        page_match = re.match(r"^\[Page\s+(\d+)\]$", line, re.IGNORECASE)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        matches = list(_LABEL_PATTERN.finditer(line))
        if not matches:
            if pending_field:
                field_key, display_label = pending_field
                results.append({
                    "field_key": field_key, "label": display_label, "value": line,
                    "page_number": current_page, "source_line": f"{display_label}: {line}"
                })
                pending_field = None
            continue

        pending_field = None
        for index, match in enumerate(matches):
            normalized = re.sub(r"[^a-z0-9]+", " ", match.group("label").lower()).strip()
            lookup = _LABEL_LOOKUP.get(normalized)
            if not lookup:
                continue
            field_key, display_label = lookup

            # A bare "Name" label is only a person-name field when it starts
            # the line/column or is explicitly qualified by candidate/applicant/student.
            # This avoids treating "Bank Name:" as the candidate's name.
            if normalized == "name":
                prefix = line[:match.start()].strip().casefold()
                if prefix not in {"", "candidate", "applicant", "student"}:
                    continue

            value_start = match.end()
            value_end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            value = line[value_start:value_end].strip(" \t:：-–—")
            if value:
                results.append({
                    "field_key": field_key, "label": display_label, "value": value,
                    "page_number": current_page,
                    "source_line": f"{match.group('label').strip()}: {value}"
                })
            else:
                pending_field = (field_key, display_label)

    return results
