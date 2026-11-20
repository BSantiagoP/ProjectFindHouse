"""Twilio SMS via the Messaging Service that holds the verified A2P 10DLC campaign."""

import httpx

from app.notifications.digest import SmsResult


class TwilioSender:
    def __init__(self, account_sid: str, auth_token: str, messaging_service_sid: str,
                 *, client: httpx.Client | None = None) -> None:
        if not (account_sid and auth_token and messaging_service_sid):
            raise ValueError("Twilio account SID, auth token and messaging service SID are required")
        self._sid = account_sid
        self._service = messaging_service_sid
        self._client = client or httpx.Client(
            base_url="https://api.twilio.com/2010-04-01", auth=(account_sid, auth_token), timeout=30,
        )

    def send(self, to: str, body: str) -> SmsResult:
        try:
            resp = self._client.post(
                f"/Accounts/{self._sid}/Messages.json",
                data={"To": to, "MessagingServiceSid": self._service, "Body": body},
            )
        except httpx.HTTPError as exc:
            return SmsResult(error=f"network error: {exc}")
        data = resp.json() if resp.content else {}
        if resp.status_code in (200, 201) and data.get("sid"):
            return SmsResult(sid=data["sid"])
        return SmsResult(error_code=data.get("code"), error=f"HTTP {resp.status_code}: {data.get('message', resp.text[:200])}")
