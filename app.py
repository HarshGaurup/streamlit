"""
Streamlit UI: meeting URL, bot name, deal picker (CRM), and meeting join POST.
- Deals and join: fixed Bearer token in code (no token field in UI).
- Join URL: PROSHORT_MEETING_JOIN_BASE_URL (default staging internal host).
- Join body matches MeetingRequest: meeting_url, bot_name, deal_id, avatar_id, voice_id.
"""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BOT_NAME = "Proshort AI Assistant"
API_BEARER_TOKEN = "ps_rocks_letmein"
DEFAULT_AVATAR_ID = "30fa96d0-26c4-4e55-94a0-517025942e18"  # Cara
DEFAULT_VOICE_ID = "6bfbe25a-979d-40f3-a92b-5394170af54b"
DEALS_PATH = "/avatar/deals"
MEETING_JOIN_PATH = "/avatar/meeting/join"
DEFAULT_MEETING_JOIN_BASE = "https://api-services-staging-apps.internal.proshort.ai/enterprise-api-down"


def _raw_jwt(credential: str) -> str:
    """Strip surrounding whitespace and a single leading 'Bearer ' (case-insensitive)."""
    t = credential.strip()
    while t.lower().startswith("bearer "):
        t = t[7:].lstrip()
    return t


def _request_headers_for_base(base_url: str, bearer_token: str) -> dict[str, str]:
    """Headers for backend requests; ngrok free tier returns HTML unless this header is set."""
    h: dict[str, str] = {
        "accept": "application/json",
        "Authorization": bearer_token,
        "origin": "https://app.proshort.ai",
        "referer": "https://app.proshort.ai/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
        ),
    }
    if "ngrok" in base_url.lower():
        h["ngrok-skip-browser-warning"] = "true"
    return h


def fetch_deals(
    base_url: str,
    bearer_token: str,
    search_term: str,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    url = f"{base_url.rstrip('/')}{DEALS_PATH}"
    params = {"customer_id": "yddizafz", "search_term": search_term or "", "limit": limit}
    headers = _request_headers_for_base(base_url, bearer_token)
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        if not (r.text or "").strip():
            return [], f"Empty response body (HTTP {r.status_code})"
        try:
            payload = r.json()
        except ValueError as e:
            snippet = (r.text or "")[:300].replace("\n", " ")
            return [], (
                f"Response was not JSON (HTTP {r.status_code}, "
                f"Content-Type: {r.headers.get('content-type', '?')!r}): {e!s}. "
                f"Body starts with: {snippet!r}"
            )
    except requests.RequestException as e:
        return [], str(e)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return [], "Unexpected response: missing or invalid `data` array"
    return data, None


def join_meeting(
    join_base_url: str,
    meeting_url: str,
    bot_name: str,
    deal_id: str,
    avatar_id: str,
    voice_id: str,
) -> tuple[Any | None, int | None, str | None]:
    """POST avatar meeting/join (MeetingRequest). Returns (body, status, error)."""
    url = f"{join_base_url.rstrip('/')}{MEETING_JOIN_PATH}"
    payload = {
        "meeting_url": meeting_url.strip(),
        "bot_name": bot_name.strip() or DEFAULT_BOT_NAME,
        "deal_id": deal_id.strip(),
        "customer_id": "yddizafz",
        "avatar_id": (avatar_id.strip() or DEFAULT_AVATAR_ID),
        "voice_id": (voice_id.strip() or DEFAULT_VOICE_ID),
    }
    headers = {
        "Content-Type": "application/json",
        "accept": "application/json",
        "Authorization": API_BEARER_TOKEN,
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as e:
        return None, None, str(e)
    ct = (r.headers.get("content-type") or "").lower()
    body: Any = None
    if "application/json" in ct:
        try:
            body = r.json()
        except ValueError:
            body = r.text
    else:
        body = r.text if r.text else None
    if not r.ok:
        err = f"HTTP {r.status_code}"
        if body is not None:
            err = f"{err}: {body!r}"
        return body, r.status_code, err
    return body, r.status_code, None


def main() -> None:
    st.set_page_config(page_title="Meeting bot setup", layout="centered")
    st.title("Meeting bot setup")

    with st.sidebar:
        st.subheader("Backend")
        api_base = st.text_input(
            "Backend base URL",
            value=os.getenv(
                "PROSHORT_MEETING_JOIN_BASE_URL",
                DEFAULT_MEETING_JOIN_BASE,
            ),
            help="Host for enterprise avatar/deals API (no trailing path).",
        )

    meeting_url = st.text_input("Meeting URL", placeholder="https://...")
    bot_name = st.text_input("Bot name", value=DEFAULT_BOT_NAME)

    st.subheader("Avatar & voice (optional)")
    col_av, col_vo = st.columns(2)
    with col_av:
        avatar_id_input = st.text_input(
            "Avatar ID",
            value=DEFAULT_AVATAR_ID,
            help="Leave default or paste another avatar UUID.",
        )
    with col_vo:
        voice_id_input = st.text_input(
            "Voice ID",
            value=DEFAULT_VOICE_ID,
            help="Leave default or paste another voice UUID.",
        )
    avatar_for_join = (avatar_id_input or "").strip() or DEFAULT_AVATAR_ID
    voice_for_join = (voice_id_input or "").strip() or DEFAULT_VOICE_ID

    st.subheader("Deal")
    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_a:
        deal_search = st.text_input(
            "Search deals",
            value="",
            placeholder="e.g. company or deal name",
        )
    with col_b:
        deal_limit = st.number_input("Limit", min_value=1, max_value=500, value=100)
    with col_c:
        st.write("")
        st.write("")
        load_clicked = st.button("Load deals", type="primary")

    if "deals_cache" not in st.session_state:
        st.session_state.deals_cache = []
    if "deals_error" not in st.session_state:
        st.session_state.deals_error = None

    if load_clicked:
        deals, err = fetch_deals(api_base, API_BEARER_TOKEN, deal_search, int(deal_limit))
        st.session_state.deals_cache = deals
        st.session_state.deals_error = err

    if st.session_state.deals_error:
        st.error(st.session_state.deals_error)
    deals = st.session_state.deals_cache

    deal_id_selected: str | None = None
    if deals:
        labels: list[str] = []
        id_by_label: dict[str, str] = {}
        for row in deals:
            if not isinstance(row, dict):
                continue
            name = str(row.get("deal_name") or "—")
            did = str(row.get("id"))
            if not did:
                continue
            label = f"{name}"
            labels.append(label)
            id_by_label[label] = did
        if labels:
            choice = st.selectbox("Deal", options=labels, index=0)
            deal_id_selected = id_by_label.get(choice)
        else:
            st.info("No deals with a usable `deal_id` in the response.")
    elif load_clicked and not st.session_state.deals_error:
        st.info("No deals returned for this search.")

    deal_id_final = (deal_id_selected or "").strip()

    st.divider()
    join_ready = bool(meeting_url.strip()) and bool(deal_id_final)
    name_for_join = (bot_name or "").strip() or DEFAULT_BOT_NAME

    col_j1, col_j2 = st.columns(2)
    with col_j1:
        join_clicked = st.button(
            "Join meeting",
            type="primary",
            disabled=not join_ready,
            help="Requires meeting URL and a deal selected from Load deals.",
        )
    with col_j2:
        review_clicked = st.button("Review selection")

    if review_clicked:
        st.json(
            {
                "meeting_url": meeting_url.strip() or None,
                "bot_name": name_for_join,
                "deal_id": deal_id_final or None,
                "avatar_id": avatar_for_join,
                "voice_id": voice_for_join,
            }
        )

    if join_clicked:
        body, status, err = join_meeting(
            api_base,
            meeting_url.strip(),
            name_for_join,
            deal_id_final,
            avatar_for_join,
            voice_for_join,
        )
        if err:
            st.error(err)
            if body is not None:
                if isinstance(body, (dict, list)):
                    st.json(body)
                else:
                    st.code(str(body))
        else:
            st.success(f"Meeting join request accepted (HTTP {status}).")
            if body is not None:
                if isinstance(body, (dict, list)):
                    st.json(body)
                else:
                    st.code(str(body))


if __name__ == "__main__":
    main()
