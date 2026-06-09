import json
import requests
import pandas as pd
import streamlit as st
from pathlib import Path

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Nursing Home Search — ABDM HFR",
    page_icon="🏥",
    layout="wide",
)

# ── API key ───────────────────────────────────────────────────────────────────
# On Streamlit Community Cloud: add api_key to the app's Secrets panel.
# Locally: reads from api_key.txt.

try:
    API_KEY = st.secrets["api_key"]
except Exception:
    _key_file = Path(__file__).parent / "api_key.txt"
    API_KEY = _key_file.read_text(encoding="utf-8").strip() if _key_file.exists() else ""

# ── District data ─────────────────────────────────────────────────────────────

@st.cache_data
def load_districts() -> list[dict]:
    with (Path(__file__).parent / "districts.json").open(encoding="utf-8") as f:
        return json.load(f)

DISTRICTS_DATA = load_districts()

# ── API ───────────────────────────────────────────────────────────────────────

SEARCH_URL = "https://apinhpr.abdm.gov.in/v4/hfr/facility/search/searchFacility"
HEADERS = {
    "apikey": API_KEY,
    "content-type": "application/json",
    "origin": "https://nhpr.abdm.gov.in",
    "referer": "https://nhpr.abdm.gov.in/",
}


def search_nursing(state_code: str, district_code: str = "") -> tuple[list[dict], int]:
    payload = {
        "searchBy": "FAC_NAME",
        "searchInput": "nursing",
        "state": state_code,
        "dist": district_code,
        "facilityType": "",
        "ownerShip": [],
        "specialty": "",
        "systemOfMedicine": "",
        "daysOfOperation": "",
        "additionalService": [],
        "onlineBooking": "",
        "orderBy": "asc",
        "abdm": "",
    }
    resp = requests.post(
        SEARCH_URL,
        headers=HEADERS,
        params={"pageNo": 0, "pageSize": 20},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return [_parse_facility(fac) for fac in data.get("content", [])], data.get("totalElements", 0)


def _parse_facility(fac: dict) -> dict:
    med = fac.get("medicalInfraRequestDTO") or []
    beds = med[0] if med else {}
    state_obj = fac.get("state") or {}
    district_obj = fac.get("district") or {}
    specialities = ", ".join(
        s.get("specName", "").strip()
        for s in (fac.get("specialityDtls") or [])
        if s.get("activeYn", "").strip() == "Y"
    )
    address = ", ".join(
        p for p in [fac.get("address1") or "", fac.get("address2") or ""] if p
    )
    return {
        "Name": fac.get("facName"),
        "Facility ID": fac.get("alternateId"),
        "Facility Type": fac.get("facilityType"),
        "Ownership": fac.get("facOwnership"),
        "Services": fac.get("typeOfService"),
        "Address": address,
        "District": district_obj.get("locName"),
        "State": state_obj.get("locName"),
        "Pincode": fac.get("pincode"),
        "Phone": fac.get("mobileNo"),
        "Email": fac.get("facEmail"),
        "Total Beds": beds.get("totalBeds") or 0,
        "ICU (vented)": beds.get("icuBedsWithVent") or 0,
        "ICU (no vent)": beds.get("icuBedsWithoutVent") or 0,
        "HDU": beds.get("hduBedsWithFuncVent") or 0,
        "Ventilators": beds.get("ventillators") or 0,
        "Pharmacy": beds.get("pharmacyPresent"),
        "Blood Bank": beds.get("bloodPresent"),
        "Dialysis": beds.get("dialysisPresent"),
        "Diag Lab": beds.get("diagPresent"),
        "Imaging": beds.get("imagingPresent"),
        "Specialities": specialities,
        "Year Est.": fac.get("yearOfEstablish"),
    }

# ── Session state ─────────────────────────────────────────────────────────────

if "queue" not in st.session_state:
    st.session_state.queue = []
if "results" not in st.session_state:
    st.session_state.results = None

# ── UI ────────────────────────────────────────────────────────────────────────

st.title("Nursing Home Search")
st.caption(
    "Searches the ABDM Health Facility Registry for facilities matching 'nursing' · "
    "up to 20 results per location · queue multiple state/district combinations and download as CSV"
)
st.divider()

left, right = st.columns([1, 2], gap="large")

with left:
    st.subheader("Build your search queue")

    state_names = [s["state_name"] for s in DISTRICTS_DATA]
    selected_state_name = st.selectbox("State", state_names)

    state_obj = next(s for s in DISTRICTS_DATA if s["state_name"] == selected_state_name)
    districts = state_obj.get("districts") or []

    district_options = ["— All districts (state level) —"] + [d["name"] for d in districts]
    selected_district_name = st.selectbox("District", district_options)

    if st.button("Add to queue", use_container_width=True):
        if selected_district_name == "— All districts (state level) —":
            entry = {
                "label": selected_state_name,
                "state_code": state_obj["state_code"],
                "district_code": "",
            }
        else:
            dist_obj = next(d for d in districts if d["name"] == selected_district_name)
            entry = {
                "label": f"{selected_state_name} › {selected_district_name}",
                "state_code": state_obj["state_code"],
                "district_code": dist_obj["code"],
            }

        existing = {(q["state_code"], q["district_code"]) for q in st.session_state.queue}
        if (entry["state_code"], entry["district_code"]) not in existing:
            st.session_state.queue.append(entry)
        else:
            st.warning("Already in queue.")

    st.divider()

    if st.session_state.queue:
        n = len(st.session_state.queue)
        st.markdown(f"**Queue — {n} location{'s' if n != 1 else ''}:**")

        remove_idx = None
        for i, entry in enumerate(st.session_state.queue):
            c1, c2 = st.columns([5, 1])
            c1.write(entry["label"])
            if c2.button("✕", key=f"rm_{i}", help="Remove"):
                remove_idx = i

        if remove_idx is not None:
            st.session_state.queue.pop(remove_idx)
            st.rerun()

        st.markdown("")

        if st.button("Run search", type="primary", use_container_width=True):
            all_rows = []
            bar = st.progress(0)
            status = st.empty()
            total_locations = len(st.session_state.queue)

            for i, entry in enumerate(st.session_state.queue):
                status.write(f"Searching {entry['label']}...")
                try:
                    facilities, total = search_nursing(entry["state_code"], entry["district_code"])
                    for fac in facilities:
                        fac["Search Location"] = entry["label"]
                        fac["Total in Registry"] = total
                    all_rows.extend(facilities)
                except Exception as e:
                    st.error(f"Error — {entry['label']}: {e}")
                bar.progress((i + 1) / total_locations)

            bar.empty()
            status.empty()
            st.session_state.results = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()

        if st.button("Clear queue", use_container_width=True):
            st.session_state.queue = []
            st.rerun()

    else:
        st.info("Add at least one location above, then click **Run search**.")

with right:
    if st.session_state.results is not None:
        df = st.session_state.results
        if df.empty:
            st.warning("No results found for the selected locations.")
        else:
            front = ["Search Location", "Total in Registry"]
            rest = [c for c in df.columns if c not in front]
            df = df[front + rest]

            st.subheader(f"Results — {len(df)} facilities")
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.download_button(
                label="Download CSV",
                data=df.to_csv(index=False),
                file_name="nursing_homes_abdm.csv",
                mime="text/csv",
                type="primary",
            )
    else:
        st.info("Results will appear here after you run the search.")
