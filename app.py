"""
Streamlit UI: meeting URL, bot name, deal picker (CRM), meeting join POST.

Metrics mode: mint a session with Anam `POST /v1/auth/session-token` (persona fields
per https://anam.ai/docs/api-reference/sessions/create-session-token), then open the
Proshort metrics page URL. `customer_id` is always from secrets (PROSHORT_CUSTOMER_ID), not the UI.

Secrets: `.streamlit/secrets.toml` — copy from `secrets.toml.example`.
Optional env: same keys via python-dotenv / `local.env`.
Metrics requires ANAM_API_KEY (optional ANAM_API_URL). Customer id is only PROSHORT_CUSTOMER_ID / env.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
load_dotenv("local.env", override=False)

DEFAULT_BOT_NAME = "Proshort AI Assistant"
DEFAULT_AVATAR_ID = "30fa96d0-26c4-4e55-94a0-517025942e18"  # Cara
DEFAULT_VOICE_ID = "6bfbe25a-979d-40f3-a92b-5394170af54b"
DEFAULT_CUSTOMER_ID = "yddizafz"
# Matches ps-enterprise-api `CUSTOM_LLM_ID`
DEFAULT_ANAM_LLM_ID = "CUSTOMER_CLIENT_V1"
DEFAULT_ANAM_API_URL = "https://api.anam.ai/v1"

DEALS_PATH = "/avatar/deals"
MEETING_JOIN_PATH = "/avatar/meeting/join"
ANAM_SESSION_TOKEN_PATH = "/auth/session-token"

# personaConfig.voiceGenerationOptions — oneOf per Anam OpenAPI (create session token)
VG_CARTESIA = "cartesia_sonic3"
VG_ELEVEN_V1 = "elevenlabs_v1"
VG_ELEVEN_V2 = "elevenlabs_v2"
VOICE_GEN_PROVIDERS = (VG_CARTESIA, VG_ELEVEN_V1, VG_ELEVEN_V2)


def build_voice_generation_options(
    provider: str,
    *,
    cartesia_volume: float,
    cartesia_speed: float,
    cartesia_emotion: str,
    el1_stability: float,
    el1_similarity_boost: float,
    el1_speed: float,
    el2_stability: float,
    el2_similarity_boost: float,
    el2_style: float,
    el2_use_speaker_boost: bool,
    el2_speed: float,
    el2_model: str,
) -> dict[str, Any]:
    """Shape matches Anam `voiceGenerationOptions` oneOf for the selected provider."""
    if provider == VG_CARTESIA:
        return {
            "volume": cartesia_volume,
            "speed": cartesia_speed,
            "emotion": cartesia_emotion,
        }
    if provider == VG_ELEVEN_V1:
        return {
            "stability": el1_stability,
            "similarityBoost": el1_similarity_boost,
            "speed": el1_speed,
        }
    if provider == VG_ELEVEN_V2:
        out: dict[str, Any] = {
            "stability": el2_stability,
            "similarityBoost": el2_similarity_boost,
            "style": el2_style,
            "useSpeakerBoost": el2_use_speaker_boost,
            "speed": el2_speed,
        }
        if (el2_model or "").strip():
            out["model"] = el2_model.strip()
        return out
    return {"volume": cartesia_volume, "speed": cartesia_speed, "emotion": cartesia_emotion}


def _secret_or_env(key: str, default: str = "") -> str:
    """Prefer env (incl. dotenv), then Streamlit secrets (local file or Cloud)."""
    v = os.getenv(key)
    if v is not None and str(v).strip():
        return str(v).strip()
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except (FileNotFoundError, RuntimeError, KeyError, TypeError):
        pass
    return default


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
    customer_id: str,
    search_term: str,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    url = f"{base_url.rstrip('/')}{DEALS_PATH}"
    params = {"customer_id": customer_id.strip(), "search_term": search_term or "", "limit": limit}
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
    customer_id: str,
    avatar_id: str,
    voice_id: str,
    bearer_token: str,
) -> tuple[Any | None, int | None, str | None]:
    """POST /avatar/meeting/join (MeetingRequest, Normal / Recall flow)."""
    endpoint = f"{join_base_url.rstrip('/')}{MEETING_JOIN_PATH}"
    cid = customer_id.strip() or DEFAULT_CUSTOMER_ID
    payload: dict[str, Any] = {
        "meeting_url": meeting_url.strip(),
        "bot_name": bot_name.strip() or DEFAULT_BOT_NAME,
        "deal_id": deal_id.strip(),
        "customer_id": cid,
        "avatar_id": (avatar_id.strip() or DEFAULT_AVATAR_ID),
        "voice_id": (voice_id.strip() or DEFAULT_VOICE_ID),
    }
    headers = {
        "Content-Type": "application/json",
        "accept": "application/json",
        "Authorization": bearer_token,
    }
    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=60)
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


def anam_create_session_token(
    anam_api_base: str,
    anam_api_key: str,
    request_body: dict[str, Any],
) -> tuple[str | None, int | None, str | None]:
    """
    POST /v1/auth/session-token — see
    https://anam.ai/docs/api-reference/sessions/create-session-token
    """
    endpoint = f"{anam_api_base.rstrip('/')}{ANAM_SESSION_TOKEN_PATH}"
    headers = {
        "Authorization": f"Bearer {anam_api_key.strip()}",
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    try:
        r = requests.post(endpoint, json=request_body, headers=headers, timeout=60)
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
        return None, r.status_code, err
    if isinstance(body, dict) and body.get("sessionToken"):
        return str(body["sessionToken"]), r.status_code, None
    return None, r.status_code, f"Unexpected response: {body!r}"


def metrics_page_url(api_base: str, deal_id: str, customer_id: str, session_token: str) -> str:
    """Same path pattern as ps-enterprise-api `page-metrics` route."""
    b = api_base.rstrip("/")
    return f"{b}/avatar/page-metrics/{deal_id.strip()}/{customer_id.strip()}/{session_token}"


def _render_metrics_open_tab(last_url: str) -> None:
    st.link_button("Open metrics page in new tab", url=last_url, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Meeting bot setup", layout="centered")
    st.title("Meeting bot setup")

    api_bearer = _secret_or_env("PROSHORT_API_BEARER_TOKEN")
    backend_from_secrets = _secret_or_env("PROSHORT_MEETING_JOIN_BASE_URL")

    with st.sidebar:
        st.subheader("Backend")
        if backend_from_secrets:
            st.caption("Backend base URL is loaded from secrets (hidden from the UI).")
        backend_override = st.text_input(
            "Backend base URL override",
            value="",
            placeholder=(
                "Leave empty to use secrets"
                if backend_from_secrets
                else "https://…/enterprise-api-down (required if unset in secrets)"
            ),
            help="Optional override. If empty, PROSHORT_MEETING_JOIN_BASE_URL from secrets or env is used.",
        )
        api_base = (backend_override.strip() or backend_from_secrets).strip()
        if not api_bearer:
            st.error(
                "Missing **PROSHORT_API_BEARER_TOKEN**. "
                "Locally: add to `.streamlit/secrets.toml`. "
                "Cloud: App → Settings → Secrets."
            )
        elif not (api_base or "").strip():
            st.warning("Set backend base URL (or PROSHORT_MEETING_JOIN_BASE_URL in secrets).")

    ui_mode = st.radio(
        "Join mode",
        options=["Normal", "Metrics"],
        index=0,
        horizontal=True,
        help="Metrics: Anam session token + Proshort metrics page (customer_id from secrets).",
    )
    use_metrics = ui_mode == "Metrics"

    # Anam persona defaults (Metrics + Anam API path); always defined for static analysis
    pc_name = "Sales Assistant"
    pc_avatar_model = "cara-3"
    pc_llm = DEFAULT_ANAM_LLM_ID
    pc_max_sec = 3600
    pc_skip_greet = False
    pc_uninterrupt = False
    pc_lang = ""
    vd_eos = 0.2
    vd_skip = 10
    vd_sess_end = 60
    vd_turn = 5.0
    vd_enh = 0.95
    vg_provider = VG_CARTESIA
    ce_vol = 0.85
    ce_spd = 1.05
    ce_emo = "content"
    el1_stability = 0.5
    el1_sim = 0.5
    el1_speed = 1.0
    el2_stability = 0.5
    el2_sim = 0.75
    el2_style = 0.0
    el2_boost = True
    el2_speed = 1.0
    el2_model = ""
    client_label = ""
    so_replay = True
    so_vq = "high"

    meeting_url = ""
    bot_name = ""
    if use_metrics:
        st.caption(
            "Metrics: [Anam create session token](https://anam.ai/docs/api-reference/sessions/create-session-token) "
            "with the persona fields below. **Customer ID** is only read from `PROSHORT_CUSTOMER_ID` in secrets."
        )
    else:
        meeting_url = st.text_input(
            "Meeting URL",
            placeholder="https://...",
            help="Required for Normal mode.",
        )
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

    customer_id_backend = _secret_or_env("PROSHORT_CUSTOMER_ID", DEFAULT_CUSTOMER_ID).strip() or DEFAULT_CUSTOMER_ID

    if use_metrics:
        if not _secret_or_env("ANAM_API_KEY"):
            st.warning(
                "Set **ANAM_API_KEY** in secrets or env to mint tokens. "
                "Optional: **ANAM_API_URL** (default `https://api.anam.ai/v1`)."
            )
        with st.expander("Anam personaConfig (defaults match ps-enterprise-api + Anam OpenAPI)", expanded=True):
                st.markdown(
                    "Ephemeral persona: set `avatarId` / `voiceId` / `llmId` / etc. "
                    "See [create session token](https://anam.ai/docs/api-reference/sessions/create-session-token)."
                )
                pc_name = st.text_input("personaConfig.name", value=pc_name)
                pc_avatar_model = st.selectbox(
                    "personaConfig.avatarModel",
                    options=["cara-2", "cara-3", "cara-4-latest"],
                    index=["cara-2", "cara-3", "cara-4-latest"].index(pc_avatar_model)
                    if pc_avatar_model in ("cara-2", "cara-3", "cara-4-latest")
                    else 1,
                )
                pc_llm = st.text_input("personaConfig.llmId", value=pc_llm)
                pc_max_sec = int(
                    st.number_input(
                        "personaConfig.maxSessionLengthSeconds",
                        min_value=60,
                        max_value=86400,
                        value=int(pc_max_sec),
                        step=60,
                    )
                )
                c1, c2, c3 = st.columns(3)
                with c1:
                    pc_skip_greet = st.checkbox("personaConfig.skipGreeting", value=pc_skip_greet)
                with c2:
                    pc_uninterrupt = st.checkbox(
                        "personaConfig.uninterruptibleGreeting",
                        value=pc_uninterrupt,
                    )
                with c3:
                    pc_lang = st.text_input(
                        "personaConfig.languageCode (optional ISO 639-1)",
                        value=pc_lang,
                    )
                st.markdown("**personaConfig.voiceDetectionOptions**")
                vd1, vd2 = st.columns(2)
                with vd1:
                    vd_eos = st.slider(
                        "endOfSpeechSensitivity",
                        0.0,
                        1.0,
                        float(vd_eos),
                        0.05,
                    )
                    vd_skip = st.number_input(
                        "silenceBeforeSkipTurnSeconds",
                        min_value=2,
                        max_value=30,
                        value=int(vd_skip),
                    )
                    vd_sess_end = st.number_input(
                        "silenceBeforeSessionEndSeconds",
                        min_value=0,
                        max_value=600,
                        value=int(vd_sess_end),
                    )
                with vd2:
                    vd_turn = st.number_input(
                        "silenceBeforeAutoEndTurnSeconds",
                        min_value=0.5,
                        max_value=10.0,
                        value=float(vd_turn),
                        step=0.5,
                    )
                    vd_enh = st.slider(
                        "speechEnhancementLevel",
                        0.0,
                        1.0,
                        float(vd_enh),
                        0.05,
                    )

                st.markdown(
                    "**personaConfig.voiceGenerationOptions** — pick provider "
                    "([Anam oneOf](https://anam.ai/docs/api-reference/sessions/create-session-token)): "
                    "Cartesia Sonic-3, ElevenLabs V1, or ElevenLabs V2."
                )
                vg_provider = st.radio(
                    "Provider",
                    options=list(VOICE_GEN_PROVIDERS),
                    index=VOICE_GEN_PROVIDERS.index(vg_provider)
                    if vg_provider in VOICE_GEN_PROVIDERS
                    else 0,
                    horizontal=True,
                    format_func=lambda p: {
                        VG_CARTESIA: "Cartesia Sonic-3",
                        VG_ELEVEN_V1: "ElevenLabs V1",
                        VG_ELEVEN_V2: "ElevenLabs V2",
                    }[p],
                    key="vg_provider_radio",
                )
                if vg_provider == VG_CARTESIA:
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        ce_vol = st.number_input(
                            "volume (0.5–2)",
                            min_value=0.5,
                            max_value=2.0,
                            value=float(ce_vol),
                            step=0.05,
                        )
                    with c2:
                        ce_spd = st.number_input(
                            "speed (0.6–1.5)",
                            min_value=0.6,
                            max_value=1.5,
                            value=float(ce_spd),
                            step=0.05,
                        )
                    with c3:
                        em_opts = ["neutral", "calm", "angry", "content", "sad", "scared"]
                        ce_emo = st.selectbox(
                            "emotion",
                            options=em_opts,
                            index=em_opts.index(ce_emo) if ce_emo in em_opts else 4,
                        )
                elif vg_provider == VG_ELEVEN_V1:
                    st.caption("ElevenLabs V1 — `stability`, `similarityBoost`, `speed`")
                    e1a, e1b, e1c = st.columns(3)
                    with e1a:
                        el1_stability = st.slider(
                            "stability",
                            0.0,
                            1.0,
                            float(el1_stability),
                            0.05,
                        )
                    with e1b:
                        el1_sim = st.slider(
                            "similarityBoost",
                            0.0,
                            1.0,
                            float(el1_sim),
                            0.05,
                        )
                    with e1c:
                        el1_speed = st.number_input(
                            "speed (0.7–1.2)",
                            min_value=0.7,
                            max_value=1.2,
                            value=float(el1_speed),
                            step=0.05,
                        )
                else:
                    st.caption(
                        "ElevenLabs V2 — `stability`, `similarityBoost`, `style`, "
                        "`useSpeakerBoost`, `speed`, optional `model`"
                    )
                    e2a, e2b, e2c = st.columns(3)
                    with e2a:
                        el2_stability = st.slider(
                            "stability",
                            0.0,
                            1.0,
                            float(el2_stability),
                            0.05,
                        )
                    with e2b:
                        el2_sim = st.slider(
                            "similarityBoost",
                            0.0,
                            1.0,
                            float(el2_sim),
                            0.05,
                        )
                    with e2c:
                        el2_style = st.slider(
                            "style (keep low for latency)",
                            0.0,
                            1.0,
                            float(el2_style),
                            0.05,
                        )
                    e2d, e2e, e2f = st.columns(3)
                    with e2d:
                        el2_boost = st.checkbox(
                            "useSpeakerBoost",
                            value=el2_boost,
                        )
                    with e2e:
                        el2_speed = st.number_input(
                            "speed (0.7–1.2)",
                            min_value=0.7,
                            max_value=1.2,
                            value=float(el2_speed),
                            step=0.05,
                        )
                    with e2f:
                        el2_model = st.text_input(
                            "model (optional ElevenLabs model id)",
                            value=el2_model,
                        )

                st.markdown("**sessionOptions** (optional)")
                so1, so2 = st.columns(2)
                with so1:
                    so_replay = st.checkbox(
                        "sessionOptions.sessionReplay.enableSessionReplay",
                        value=so_replay,
                    )
                with so2:
                    vq_opts = ["high", "auto"]
                    so_vq = st.selectbox(
                        "sessionOptions.videoQuality",
                        options=vq_opts,
                        index=vq_opts.index(so_vq) if so_vq in vq_opts else 0,
                    )

                client_label = st.text_input(
                    "clientLabel (optional)",
                    value=client_label,
                )

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
        if not api_bearer:
            deals, err = [], "Set PROSHORT_API_BEARER_TOKEN in secrets or environment."
        elif not (api_base or "").strip():
            deals, err = [], "Enter a backend base URL."
        else:
            deals, err = fetch_deals(
                api_base, api_bearer, customer_id_backend, deal_search, int(deal_limit)
            )
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

    # Metrics actions (below deal section): Anam API only
    if use_metrics:
        st.divider()
        st.subheader("Metrics session")
        anam_key = _secret_or_env("ANAM_API_KEY")
        anam_url_base = _secret_or_env("ANAM_API_URL", DEFAULT_ANAM_API_URL)
        st.caption(
            f"Anam base: `{anam_url_base}` — endpoint `{ANAM_SESSION_TOKEN_PATH}`"
        )

        persona_config: dict[str, Any] = {
            "name": pc_name.strip() or "Sales Assistant",
            "avatarId": avatar_for_join,
            "avatarModel": pc_avatar_model,
            "voiceId": voice_for_join,
            "llmId": pc_llm.strip() or DEFAULT_ANAM_LLM_ID,
            "voiceDetectionOptions": {
                "endOfSpeechSensitivity": float(vd_eos),
                "silenceBeforeSkipTurnSeconds": int(vd_skip),
                "silenceBeforeSessionEndSeconds": int(vd_sess_end),
                "silenceBeforeAutoEndTurnSeconds": float(vd_turn),
                "speechEnhancementLevel": float(vd_enh),
            },
            "skipGreeting": pc_skip_greet,
            "voiceGenerationOptions": build_voice_generation_options(
                vg_provider,
                cartesia_volume=float(ce_vol),
                cartesia_speed=float(ce_spd),
                cartesia_emotion=str(ce_emo),
                el1_stability=float(el1_stability),
                el1_similarity_boost=float(el1_sim),
                el1_speed=float(el1_speed),
                el2_stability=float(el2_stability),
                el2_similarity_boost=float(el2_sim),
                el2_style=float(el2_style),
                el2_use_speaker_boost=bool(el2_boost),
                el2_speed=float(el2_speed),
                el2_model=str(el2_model),
            ),
            "maxSessionLengthSeconds": int(pc_max_sec),
        }
        if pc_uninterrupt:
            persona_config["uninterruptibleGreeting"] = True
        if pc_lang.strip():
            persona_config["languageCode"] = pc_lang.strip()

        anam_body: dict[str, Any] = {"personaConfig": persona_config}
        if client_label.strip():
            anam_body["clientLabel"] = client_label.strip()
        anam_body["sessionOptions"] = {
            "sessionReplay": {"enableSessionReplay": bool(so_replay)},
            "videoQuality": so_vq,
        }

        with st.expander("POST body preview (Anam)"):
            st.code(json.dumps(anam_body, indent=2), language="json")

        go_anam = st.button(
            "Mint session token & build metrics URL",
            type="primary",
            disabled=not (bool(deal_id_final) and bool(anam_key)),
            key="btn_metrics_anam",
        )
        if go_anam:
            if not (api_base or "").strip():
                st.error("Backend base URL is required to build the Proshort metrics page link.")
            elif not anam_key:
                st.error("Set ANAM_API_KEY.")
            else:
                token, status, err = anam_create_session_token(
                    anam_url_base, anam_key, anam_body
                )
                if err or not token:
                    st.error(err or "No session token")
                else:
                    st.success(f"Anam session token minted (HTTP {status}).")
                    built = metrics_page_url(
                        api_base, deal_id_final, customer_id_backend, token
                    )
                    st.session_state["metrics_last_url"] = built
                    st.json({"sessionToken": token[:24] + "…", "metrics_page_url": built})

    if not use_metrics:
        st.divider()
        meeting_ok = bool(meeting_url.strip())
        join_ready = bool(deal_id_final) and meeting_ok
        name_for_join = (bot_name or "").strip() or DEFAULT_BOT_NAME

        col_j1, col_j2 = st.columns(2)
        with col_j1:
            join_clicked = st.button(
                "Join meeting",
                type="primary",
                disabled=not join_ready,
                help="Requires meeting URL and a deal from Load deals.",
            )
        with col_j2:
            review_clicked = st.button("Review selection")

        if review_clicked:
            preview_nm: dict[str, Any] = {
                "deal_id": deal_id_final or None,
                "avatar_id": avatar_for_join,
                "voice_id": voice_for_join,
                "customer_id": customer_id_backend,
                "meeting_url": meeting_url.strip() or None,
                "bot_name": name_for_join or DEFAULT_BOT_NAME,
            }
            st.json(preview_nm)

        if join_clicked:
            cid_join = customer_id_backend
            if not api_bearer:
                st.error("Set PROSHORT_API_BEARER_TOKEN before joining.")
            elif not (api_base or "").strip():
                st.error("Enter a backend base URL before joining.")
            else:
                body, status, err = join_meeting(
                    api_base,
                    meeting_url.strip(),
                    name_for_join,
                    deal_id_final,
                    cid_join,
                    avatar_for_join,
                    voice_for_join,
                    api_bearer,
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

    last = st.session_state.get("metrics_last_url")
    if last and use_metrics:
        _render_metrics_open_tab(last)


if __name__ == "__main__":
    main()
