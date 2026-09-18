"""Tests for the log scrubber.

Logs are the easiest place for resume content to leak, so this is treated as a
privacy control and tested as one.
"""

from __future__ import annotations

from roleva.telemetry.logging import scrub_content


def scrub(**fields: object) -> dict[str, object]:
    return dict(scrub_content(None, "info", dict(fields)))


class TestContentIsNeverLogged:
    def test_resume_text_is_replaced_with_a_fingerprint(self) -> None:
        result = scrub(event="parsed", resume_text="Priya built a Django service")
        assert "Priya" not in str(result["resume_text"])
        assert "redacted" in str(result["resume_text"])

    def test_the_fingerprint_still_allows_correlation(self) -> None:
        a = scrub(text="same content")["text"]
        b = scrub(text="same content")["text"]
        c = scrub(text="different content")["text"]
        assert a == b
        assert a != c

    def test_prompts_and_responses_are_scrubbed(self) -> None:
        result = scrub(prompt="Extract from: Priya", response="Zoho Corporation")
        assert "Priya" not in str(result["prompt"])
        assert "Zoho" not in str(result["response"])

    def test_contact_fields_are_scrubbed(self) -> None:
        result = scrub(name="Priya Raghavan", email="p@example.com", phone="9876543210")
        assert "Priya" not in str(result["name"])
        assert "p@example.com" not in str(result["email"])
        assert "9876543210" not in str(result["phone"])


class TestSecretsAreNeverLogged:
    def test_keys_and_tokens_are_masked(self) -> None:
        result = scrub(api_key="AQ.secret", token="ey.secret", password="hunter2")
        assert result["api_key"] == "<secret>"
        assert result["token"] == "<secret>"
        assert result["password"] == "<secret>"


class TestValueScanning:
    """Catches content that arrives under an innocent-looking key name."""

    def test_an_email_hidden_in_a_message_is_masked(self) -> None:
        result = scrub(detail="failed for priya@example.com")
        assert "priya@example.com" not in str(result["detail"])
        assert "<email>" in str(result["detail"])

    def test_a_long_digit_run_is_masked(self) -> None:
        result = scrub(detail="contact 919876543210 for details")
        assert "919876543210" not in str(result["detail"])


class TestOperationalFieldsSurvive:
    """Scrubbing must not make logs useless."""

    def test_metrics_and_identifiers_are_kept(self) -> None:
        result = scrub(
            event="analysis.complete",
            stage="matching",
            duration_ms=1840,
            llm_calls=5,
            user_id="8f14e45f-ea8d-4b2c",
            status=200,
        )
        assert result["event"] == "analysis.complete"
        assert result["stage"] == "matching"
        assert result["duration_ms"] == 1840
        assert result["llm_calls"] == 5
        assert result["user_id"] == "8f14e45f-ea8d-4b2c"
        assert result["status"] == 200

    def test_a_short_number_in_a_string_is_left_alone(self) -> None:
        result = scrub(detail="retried 3 times after 2 failures")
        assert result["detail"] == "retried 3 times after 2 failures"
