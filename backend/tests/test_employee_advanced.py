"""Self-check for Advanced Edit validation helpers.

Plain asserts (no pytest dependency). Run from the backend directory:

    python tests/test_employee_advanced.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.employees import (  # noqa: E402
    _advanced_date_errors, _advanced_errors, _normalize_advanced,
)


def test_formats_and_choices():
    assert _advanced_errors({"uan": "123456789012"}) == []
    assert _advanced_errors({"uan": "12345"}) == ["Invalid UAN format (12 digits)"]
    assert _advanced_errors({"esic_ip_number": "1234567890"}) == []
    assert _advanced_errors({"esic_ip_number": "abc"} ) == [
        "Invalid ESIC IP Number format (10-17 digits)"]
    assert _advanced_errors({"pf_member_id": "MH/BAN/12345/000/0001234"}) == []
    assert _advanced_errors({"pf_member_id": "!!"}) == ["Invalid PF Member ID format"]
    assert _advanced_errors({"pf_applicable": "Pending Verification"}) == []
    assert _advanced_errors({"pf_applicable": "Maybe"}) == ["Invalid PF Applicable value"]
    # Blank / absent values are optional and never error.
    assert _advanced_errors({"uan": "", "pf_applicable": "", "job_leave_date": None}) == []


def test_normalize():
    d = {"uan": "1234 5678-9012", "esic_ip_number": "11 22 3344 55", "pf_member_id": " mh/ban/1 "}
    _normalize_advanced(d)
    assert d["uan"] == "123456789012"
    assert d["esic_ip_number"] == "1122334455"
    assert d["pf_member_id"] == "MH/BAN/1"


def test_date_order():
    assert _advanced_date_errors({
        "pf_joining_date": date(2024, 1, 1), "pf_exit_date": date(2024, 6, 1)}) == []
    assert _advanced_date_errors({
        "pf_joining_date": date(2024, 6, 1), "pf_exit_date": date(2024, 1, 1)}) == [
        "PF Exit Date cannot be before PF Joining Date"]
    assert _advanced_date_errors({
        "esic_joining_date": date(2024, 6, 1), "esic_exit_date": date(2024, 1, 1)}) == [
        "ESIC Exit Date cannot be before ESIC Joining Date"]
    assert _advanced_date_errors({
        "joining_date": date(2024, 6, 1), "job_leave_date": date(2024, 1, 1)}) == [
        "Job Leave Date cannot be before Joining Date"]


if __name__ == "__main__":
    test_formats_and_choices()
    test_normalize()
    test_date_order()
    print("Advanced Edit validation self-check passed.")
