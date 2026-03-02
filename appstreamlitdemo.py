"""
Smart Newsletter · Pipeline Ops Dashboard
==========================================
Un único fichero. Sube D0 a GCS → dispara Airflow → monitoriza via BigQuery → descarga D1.

ARRANCAR:
    pip install streamlit pandas openpyxl
    streamlit run app.py

MODO DEMO (sin variables de entorno): arranca automáticamente con simulación completa.

MODO REAL – variables de entorno:
    GCP_PROJECT_ID          smart-newsletter-dev
    GCS_BUCKET_RAW          newsletter-raw-smart-newsletter-dev
    GCS_BUCKET_OUTPUT       newsletter-output-smart-newsletter-dev
    BQ_DATASET              newsletter_data
    AIRFLOW_URL             https://xxxxx.composer.googleusercontent.com
    AIRFLOW_DAG_ID          smart_newsletter_gcp
    AIRFLOW_USER            admin
    AIRFLOW_PASS            admin
    FORGEROCK_CLIENT_ID     (ver sección AUTH)
    FORGEROCK_CLIENT_SECRET (ver sección AUTH)
    FORGEROCK_ISSUER_URL    https://am.intranet.db.com/oauth2/realms/employees
    FORGEROCK_REDIRECT_URI  http://localhost:8501

DEPENDENCIAS ADICIONALES para modo real:
    pip install google-cloud-storage google-cloud-bigquery google-auth requests authlib
"""

import os, time, uuid, random
import pandas as pd
import streamlit as st
from io import BytesIO
from datetime import datetime, timedelta

# GCP imports – solo en modo real
try:
    from google.cloud import storage as gcs_lib
    from google.cloud import bigquery as bq_lib
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# ① CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

CFG = {
    "project"       : os.getenv("GCP_PROJECT_ID", ""),
    "region"        : os.getenv("GCP_REGION", "europe-west1"),
    "bucket_raw"    : os.getenv("GCS_BUCKET_RAW", ""),
    "bucket_output" : os.getenv("GCS_BUCKET_OUTPUT", ""),
    "bq_dataset"    : os.getenv("BQ_DATASET", "newsletter_data"),
    "airflow_url"   : os.getenv("AIRFLOW_URL", ""),
    "airflow_dag"   : os.getenv("AIRFLOW_DAG_ID", "smart_newsletter_gcp"),
    "airflow_user"  : os.getenv("AIRFLOW_USER", "admin"),
    "airflow_pass"  : os.getenv("AIRFLOW_PASS", "admin"),
    "fr_client_id"  : os.getenv("FORGEROCK_CLIENT_ID", ""),
    "fr_secret"     : os.getenv("FORGEROCK_CLIENT_SECRET", ""),
    "fr_issuer"     : os.getenv("FORGEROCK_ISSUER_URL", ""),
    "fr_redirect"   : os.getenv("FORGEROCK_REDIRECT_URI", "http://localhost:8501"),
    "fr_scopes"     : os.getenv("FORGEROCK_SCOPES", "openid profile email"),
}

DEMO_MODE      = not CFG["project"] or not GCP_AVAILABLE
TARGET_LANGS   = ["ENG", "ESP", "GER", "ITA", "FRA", "CAT"]
LANG_NAMES     = {"ENG":"English","ESP":"Spanish","GER":"German",
                  "ITA":"Italian","FRA":"French","CAT":"Catalan"}
D0_REQUIRED    = ["URL_DOCUMENT", "LANGUAGE", "TOPIC", "TITLE"]
DEMO_DURATIONS = [2, 4, 6, 3, 1]  # segundos por etapa en demo

PIPELINE_STAGES = [
    {"key":"upload",      "es":"Subida GCS",    "en":"GCS Upload",    "icon":"☁️",  "service":"Cloud Storage"},
    {"key":"ingestion",   "es":"Ingesta",        "en":"Ingestion",     "icon":"📥",  "service":"Cloud Run · Ingestion"},
    {"key":"translation", "es":"Traducción",     "en":"Translation",   "icon":"🌐",  "service":"Cloud Run · Vertex AI"},
    {"key":"generation",  "es":"Generación D1",  "en":"D1 Generation", "icon":"📤",  "service":"Cloud Run · Generation"},
    {"key":"done",        "es":"Completado",     "en":"Completed",     "icon":"✅",  "service":"BigQuery · Output GCS"},
]

STATUS_TO_STAGE = {"pending":0,"processing":1,"ingested":2,"translated":3,"completed":4,"error":-1}

# ─────────────────────────────────────────────────────────────────────────────
# ② TEXTOS UI (ES / EN)
# ─────────────────────────────────────────────────────────────────────────────

TEXTS = {
"ES": {
    "tab_launch":"🚀 Lanzar Pipeline", "tab_monitor":"📡 Monitor", "tab_history":"📋 Historial",
    "demo_badge":"🟡 DEMO MODE", "real_badge":"🟢 CONECTADO A GCP",
    "launch_title":"Cargar fichero D0 y lanzar pipeline",
    "upload_label":"Selecciona un D0.xlsx",
    "upload_hint":"Columnas requeridas: URL_DOCUMENT, LANGUAGE, TOPIC, TITLE",
    "file_ok":"✅ Fichero válido", "file_docs":"documentos", "file_cols":"columnas",
    "file_err":"❌ Columnas faltantes:",
    "btn_launch":"🚀 Subir a GCS y lanzar pipeline",
    "launching":"Subiendo a GCS y disparando DAG...", "launched_ok":"✅ Pipeline lanzado",
    "order_label":"Order ID", "gcs_label":"GCS Path", "dag_label":"DAG Run ID",
    "go_monitor":"→ Ve a la pestaña **📡 Monitor** para seguir el progreso",
    "demo_warn":"⚠️ DEMO MODE — las llamadas a GCS y Airflow son simuladas.",
    "monitor_title":"Estado del Pipeline", "order_input":"Order ID a monitorizar",
    "btn_refresh":"🔄 Refrescar", "autorefresh":"Auto-refresh (5s)",
    "no_order":"Introduce un Order ID o lanza un pipeline primero.",
    "elapsed":"Tiempo", "docs_label":"Documentos", "trans_label":"Traducciones",
    "d1_ready":"🎉 D1 listo para descargar", "btn_download":"⬇️ Descargar D1",
    "bq_logs":"Logs de ejecución", "history_title":"Órdenes anteriores",
    "history_empty":"No hay órdenes en BigQuery todavía.",
    "col_order":"Order ID","col_status":"Estado","col_file":"Fichero",
    "col_docs":"Docs","col_date":"Fecha","col_dur":"Duración",
},
"EN": {
    "tab_launch":"🚀 Launch Pipeline", "tab_monitor":"📡 Monitor", "tab_history":"📋 History",
    "demo_badge":"🟡 DEMO MODE", "real_badge":"🟢 CONNECTED TO GCP",
    "launch_title":"Upload D0 file and launch pipeline",
    "upload_label":"Select a D0.xlsx file",
    "upload_hint":"Required columns: URL_DOCUMENT, LANGUAGE, TOPIC, TITLE",
    "file_ok":"✅ Valid file", "file_docs":"documents", "file_cols":"columns",
    "file_err":"❌ Missing columns:",
    "btn_launch":"🚀 Upload to GCS and launch pipeline",
    "launching":"Uploading to GCS and triggering DAG...", "launched_ok":"✅ Pipeline launched",
    "order_label":"Order ID", "gcs_label":"GCS Path", "dag_label":"DAG Run ID",
    "go_monitor":"→ Go to **📡 Monitor** tab to track progress",
    "demo_warn":"⚠️ DEMO MODE — GCS and Airflow calls are simulated.",
    "monitor_title":"Pipeline Status", "order_input":"Order ID to monitor",
    "btn_refresh":"🔄 Refresh", "autorefresh":"Auto-refresh (5s)",
    "no_order":"Enter an Order ID or launch a pipeline first.",
    "elapsed":"Elapsed", "docs_label":"Documents", "trans_label":"Translations",
    "d1_ready":"🎉 D1 ready to download", "btn_download":"⬇️ Download D1",
    "bq_logs":"Execution logs", "history_title":"Previous orders",
    "history_empty":"No orders in BigQuery yet.",
    "col_order":"Order ID","col_status":"Status","col_file":"File",
    "col_docs":"Docs","col_date":"Date","col_dur":"Duration",
},
}

# ─────────────────────────────────────────────────────────────────────────────
# ③ ESTILOS CSS
#
# TODO [COPILOT – DESIGN SYSTEM]:
#   Reemplazar los tokens de color y tipografía por los del DS oficial de DB.
#   Tokens a obtener del equipo de UX/Branding:
#     - Colores primarios exactos (actualmente: #0066B3 / #00305E)
#     - Tipografía corporativa (actualmente: IBM Plex Sans como aproximación)
#     - Si existe CDN del DS, añadir <link rel="stylesheet" href="..."> justo
#       antes del bloque <style> en inject_styles()
#   URL interna DS: TODO añadir cuando esté disponible
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

:root {
    /* TODO [COPILOT]: confirmar hex exactos con equipo UX DB */
    --primary     : #0066B3;
    --primary-dk  : #00305E;
    --primary-pale: #EAF3FB;
    --bg          : #F4F6F9;
    --surface     : #FFFFFF;
    --surface-alt : #F0F4F8;
    --border      : #DDE3EC;
    --border-lt   : #EEF1F6;
    --text        : #1A2332;
    --text-2      : #4A5568;
    --text-muted  : #8A99AD;
    --ok          : #0A7B55; --ok-bg : #ECFAF4; --ok-bd : #6EE7B7;
    --warn        : #A16207; --warn-bg: #FEFCE8; --warn-bd: #FDE047;
    --err         : #B91C1C; --err-bg : #FEF2F2; --err-bd : #FCA5A5;
    --sh-xs       : 0 1px 2px rgba(0,48,94,.05);
    --sh-sm       : 0 1px 4px rgba(0,48,94,.07),0 1px 2px rgba(0,48,94,.04);
    --sh-md       : 0 4px 12px rgba(0,48,94,.08);
    /* TODO [COPILOT]: si DB tiene fuente corporativa, reemplazar aquí */
    --font        : 'IBM Plex Sans', sans-serif;
    --mono        : 'IBM Plex Mono', monospace;
    --r-sm:6px; --r-md:10px; --r-lg:14px; --r-pill:999px;
}

html,body,[class*="css"]{ font-family:var(--font); color:var(--text); }
.stApp              { background:var(--bg); }
.block-container    { padding-top:1.5rem!important; padding-left:2rem!important;
                      padding-right:2rem!important; max-width:1140px!important; }
section[data-testid="stSidebar"]{ background:var(--surface)!important;
                                   border-right:1px solid var(--border)!important; }
.stSidebar .stRadio label,
.stSidebar .stCheckbox label { font-size:.82rem; color:var(--text-2); }
.stSidebar hr  { border-color:var(--border-lt); margin:.75rem 0; }
.stSidebar p   { font-size:.82rem; color:var(--text-2); }

/* Header */
.ops-header { background:var(--surface); border:1px solid var(--border);
              border-top:3px solid var(--primary); border-radius:var(--r-lg);
              padding:1.2rem 1.6rem; margin-bottom:1.5rem;
              display:flex; align-items:center; gap:1rem; box-shadow:var(--sh-sm); }
/* TODO [COPILOT]: reemplazar .logo-box por <img src="assets/db_logo.svg" height="40">
   cuando el asset esté disponible en el repositorio */
.logo-box   { width:44px; height:44px; background:var(--primary-dk);
              border-radius:var(--r-sm); display:flex; align-items:center;
              justify-content:center; flex-shrink:0; font-size:.65rem;
              font-weight:700; color:white; letter-spacing:.06em; font-family:var(--font); }
.hdr-title  { font-size:1.05rem; font-weight:600; color:var(--primary-dk); margin:0; line-height:1.25; }
.hdr-sub    { font-size:.72rem; color:var(--text-muted); margin:.18rem 0 0; font-family:var(--mono); }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background:var(--surface-alt); border:1px solid var(--border-lt);
                                     border-radius:var(--r-md); gap:3px; padding:4px; }
.stTabs [data-baseweb="tab"]      { background:transparent; color:var(--text-muted);
                                     border-radius:var(--r-sm); font-size:.85rem; font-weight:500; }
.stTabs [aria-selected="true"]    { background:var(--surface)!important; color:var(--primary)!important;
                                     font-weight:600!important; box-shadow:var(--sh-xs); }

/* Buttons */
.stButton>button       { background:var(--primary); color:white!important; border:none;
                          border-radius:var(--r-sm); font-weight:500; font-size:.875rem;
                          box-shadow:var(--sh-xs); transition:background .15s; }
.stButton>button:hover { background:var(--primary-dk); box-shadow:var(--sh-md); }

/* Text input */
.stTextInput input       { background:var(--surface)!important; border:1px solid var(--border)!important;
                            border-radius:var(--r-sm)!important; color:var(--text)!important; font-size:.875rem!important; }
.stTextInput input:focus { border-color:var(--primary)!important;
                            box-shadow:0 0 0 3px var(--primary-pale)!important; }

/* File uploader */
[data-testid="stFileUploader"]>div { background:var(--surface); border:2px dashed var(--border);
                                      border-radius:var(--r-md); transition:border-color .2s; }
[data-testid="stFileUploader"]>div:hover { border-color:var(--primary); }

/* DataFrames, alerts, expander */
div[data-testid="stDataFrame"] { background:var(--surface); border:1px solid var(--border)!important;
                                   border-radius:var(--r-md); box-shadow:var(--sh-xs); overflow:hidden; }
[data-testid="stAlert"]        { border-radius:var(--r-sm)!important; font-size:.85rem!important; }
.streamlit-expanderHeader      { background:var(--surface-alt); border-radius:var(--r-sm);
                                   font-size:.85rem; color:var(--text-2); }

/* Section title */
.sec-title { font-size:.68rem; font-weight:600; color:var(--text-muted); text-transform:uppercase;
             letter-spacing:.1em; font-family:var(--mono); border-bottom:1px solid var(--border-lt);
             padding-bottom:.5rem; margin-bottom:1.25rem; }

/* Info cards */
.info-card             { background:var(--surface); border:1px solid var(--border);
                          border-radius:var(--r-md); padding:1rem 1.2rem; box-shadow:var(--sh-xs); }
.info-card .card-label { font-size:.68rem; font-weight:500; color:var(--text-muted);
                          text-transform:uppercase; letter-spacing:.07em; }
.info-card .card-value { font-size:1.6rem; font-weight:700; color:var(--primary-dk);
                          margin-top:.1rem; line-height:1.15; }
.info-card .card-sub   { font-size:.7rem; color:var(--text-muted); margin-top:.2rem;
                          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* Order ID card */
.order-display          { background:var(--primary-pale); border:1px solid var(--primary);
                           border-radius:var(--r-md); padding:1.1rem 1.4rem; }
.order-display .oid-lbl { font-size:.65rem; font-weight:600; color:var(--primary);
                           text-transform:uppercase; letter-spacing:.1em; font-family:var(--mono); }
.order-display .oid-val { font-size:1.7rem; font-weight:700; color:var(--primary-dk);
                           margin-top:.1rem; letter-spacing:.08em; font-family:var(--mono); }
.order-display .oid-meta{ font-size:.7rem; color:var(--text-2); margin-top:.5rem;
                           font-family:var(--mono); line-height:1.7; }

/* Badges */
.badge-demo { background:var(--warn-bg); color:var(--warn); border:1px solid var(--warn-bd);
              padding:3px 10px; border-radius:var(--r-pill); font-size:.68rem;
              font-weight:600; font-family:var(--mono); }
.badge-real { background:var(--ok-bg);   color:var(--ok);   border:1px solid var(--ok-bd);
              padding:3px 10px; border-radius:var(--r-pill); font-size:.68rem;
              font-weight:600; font-family:var(--mono); }

/* Status pills */
.pill-pending    { display:inline-block; padding:2px 9px; border-radius:var(--r-pill); font-size:.7rem; font-weight:600; font-family:var(--mono); background:#F1F5F9;           color:#64748B; border:1px solid #CBD5E1; }
.pill-processing { display:inline-block; padding:2px 9px; border-radius:var(--r-pill); font-size:.7rem; font-weight:600; font-family:var(--mono); background:var(--primary-pale); color:var(--primary); border:1px solid #93C5FD; }
.pill-ingested   { display:inline-block; padding:2px 9px; border-radius:var(--r-pill); font-size:.7rem; font-weight:600; font-family:var(--mono); background:#EFF6FF;           color:#2563EB; border:1px solid #BFDBFE; }
.pill-translated { display:inline-block; padding:2px 9px; border-radius:var(--r-pill); font-size:.7rem; font-weight:600; font-family:var(--mono); background:#F5F3FF;           color:#7C3AED; border:1px solid #DDD6FE; }
.pill-completed  { display:inline-block; padding:2px 9px; border-radius:var(--r-pill); font-size:.7rem; font-weight:600; font-family:var(--mono); background:var(--ok-bg);      color:var(--ok);  border:1px solid var(--ok-bd); }
.pill-error      { display:inline-block; padding:2px 9px; border-radius:var(--r-pill); font-size:.7rem; font-weight:600; font-family:var(--mono); background:var(--err-bg);     color:var(--err); border:1px solid var(--err-bd); }

/* Pipeline stages */
.stage-icon        { width:50px; height:50px; border-radius:50%; display:flex;
                      align-items:center; justify-content:center; font-size:1.25rem;
                      margin:0 auto .5rem; position:relative; z-index:1; }
.stage-icon.done   { background:var(--primary-pale); border:2px solid var(--primary); }
.stage-icon.active { background:var(--primary); border:2px solid var(--primary-dk);
                      animation:pulse-soft 2s ease-in-out infinite; }
.stage-icon.wait   { background:var(--surface-alt); border:2px solid var(--border); opacity:.55; }
.stage-icon.error  { background:var(--err-bg); border:2px solid var(--err); }
@keyframes pulse-soft {
    0%,100%{ box-shadow:0 0 0 0   var(--primary-pale); }
    50%    { box-shadow:0 0 0 8px var(--primary-pale); }
}
.stage-lbl        { font-size:.7rem; font-weight:600; color:var(--text-muted);
                     font-family:var(--mono); text-align:center; }
.stage-lbl.done   { color:var(--primary); }
.stage-lbl.active { color:var(--primary-dk); font-weight:700; }
.stage-lbl.error  { color:var(--err); }
.stage-svc        { font-size:.6rem; color:var(--text-muted); text-align:center; margin-top:.1rem; }

/* Log terminal */
.log-terminal     { background:var(--surface-alt); border:1px solid var(--border);
                     border-left:3px solid var(--primary); border-radius:var(--r-sm);
                     padding:.9rem 1rem; font-family:var(--mono); font-size:.73rem;
                     color:var(--text-2); max-height:175px; overflow-y:auto; line-height:1.75; }
.log-terminal .log-ok   { color:var(--ok); }
.log-terminal .log-info { color:var(--primary); }
.log-terminal .log-warn { color:var(--warn); }
.log-terminal .log-err  { color:var(--err); }

.footer-bar { text-align:center; font-size:.68rem; color:var(--text-muted);
              font-family:var(--mono); padding:.4rem 0; }
"""

# ─────────────────────────────────────────────────────────────────────────────
# ④ AUTH – ForgeRock OIDC
#
# TODO [COPILOT]: Implementar flujo OIDC completo.
# Instalar: pip install authlib requests
#
# Flujo esperado en require_auth():
#   1. Leer st.query_params
#   2. Si hay "code" y "state" → _exchange_code() → _validate_jwt()
#   3. Guardar claims en st.session_state → st.query_params.clear() → st.rerun()
#   4. Si no hay sesión → _render_login_page() → st.stop()
#
# Endpoints ForgeRock (rellenar con URLs internas):
#   Authorize: {CFG["fr_issuer"]}/authorize
#   Token    : {CFG["fr_issuer"]}/access_token
#   UserInfo : {CFG["fr_issuer"]}/userinfo
#   JWKS     : {CFG["fr_issuer"]}/.well-known/jwks.json
#   Revoke   : {CFG["fr_issuer"]}/token/revoke
# ─────────────────────────────────────────────────────────────────────────────

DEMO_USER = {"sub":"demo-001","name":"Demo User","email":"demo.user@db.com",
             "groups":["newsletter-ops","data-engineering"]}

def require_auth() -> dict:
    """Guard de autenticación. En DEMO_MODE devuelve DEMO_USER directamente.
    TODO [COPILOT]: implementar flujo OIDC real (ver comentario sección ④)."""
    for k, v in {"user":None,"access_token":None,"authenticated":False}.items():
        if k not in st.session_state: st.session_state[k] = v
    if DEMO_MODE:
        st.session_state.update({"authenticated":True, "user":DEMO_USER})
        return DEMO_USER
    # TODO [COPILOT]: eliminar las dos líneas siguientes e implementar OIDC real
    st.session_state.update({"authenticated":True, "user":{"name":"User","email":"user@db.com"}})
    return st.session_state["user"]

def _get_auth_url() -> str:
    """TODO [COPILOT]: Construir URL OIDC con authlib OAuth2Session.
        from authlib.integrations.requests_client import OAuth2Session
        session = OAuth2Session(client_id=CFG["fr_client_id"],
                                redirect_uri=CFG["fr_redirect"], scope=CFG["fr_scopes"])
        uri, state = session.create_authorization_url(f"{CFG['fr_issuer']}/authorize")
        st.session_state["oauth_state"] = state
        return uri"""
    raise NotImplementedError("TODO: implementar _get_auth_url()")

def _exchange_code(code: str, state: str) -> dict:
    """TODO [COPILOT]:
        from authlib.integrations.requests_client import OAuth2Session
        session = OAuth2Session(client_id=CFG["fr_client_id"],
                                client_secret=CFG["fr_secret"],
                                redirect_uri=CFG["fr_redirect"], state=state)
        return session.fetch_token(f"{CFG['fr_issuer']}/access_token",
                                   code=code, grant_type="authorization_code")"""
    raise NotImplementedError("TODO: implementar _exchange_code()")

def _validate_jwt(id_token: str) -> dict:
    """TODO [COPILOT]:
        import requests
        from authlib.jose import JsonWebKey, jwt as jose_jwt
        jwks = requests.get(f"{CFG['fr_issuer']}/.well-known/jwks.json").json()
        key_set = JsonWebKey.import_key_set(jwks)
        claims = jose_jwt.decode(id_token, key_set)
        claims.validate()
        return dict(claims)"""
    raise NotImplementedError("TODO: implementar _validate_jwt()")

def logout():
    """Limpia sesión. TODO [COPILOT]: añadir revocación del token en ForgeRock."""
    for k in ["user","access_token","authenticated"]:
        st.session_state[k] = None
    st.session_state["authenticated"] = False
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# ⑤ GCP – CLOUD STORAGE
#
# TODO [COPILOT]: Descomentar código real. Instalar: pip install google-cloud-storage
# Auth local: gcloud auth application-default login
# En Cloud Run: Service Account con roles/storage.admin
# ─────────────────────────────────────────────────────────────────────────────

def gcs_upload_d0(file_bytes: bytes, filename: str, order_id: str) -> str:
    """Sube D0 a gs://{bucket_raw}/inbox/{order_id}/{filename}
    TODO [COPILOT]:
        client = gcs_lib.Client(project=CFG["project"])
        bucket = client.bucket(CFG["bucket_raw"])
        blob = bucket.blob(f"inbox/{order_id}/{filename}")
        blob.upload_from_string(file_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return f"gs://{CFG['bucket_raw']}/inbox/{order_id}/{filename}"

    Nota: si usas GCS Event Trigger (OPCIÓN B en sección ⑦), este upload es
    suficiente para arrancar el pipeline sin llamar a Airflow manualmente."""
    if DEMO_MODE:
        return f"gs://newsletter-raw-demo/inbox/{order_id}/{filename}"
    # TODO [COPILOT]: descomentar implementación real arriba
    raise NotImplementedError("TODO: implementar gcs_upload_d0()")

def gcs_get_d1(order_id: str):
    """Retorna URL firmada del D1 o bytes como fallback.
    TODO [COPILOT]:
        client = gcs_lib.Client(project=CFG["project"])
        bucket = client.bucket(CFG["bucket_output"])
        blob = bucket.blob(f"output/{order_id}/D1-{order_id}.xlsx")
        if not blob.exists(): return None
        # Opción A – URL firmada (requiere iam.serviceAccounts.signBlob):
        return blob.generate_signed_url(version="v4", expiration=3600, method="GET",
            response_disposition=f'attachment; filename="D1-{order_id}.xlsx"')
        # Opción B – bytes directos (sin permisos signBlob):
        # return blob.download_as_bytes()"""
    if DEMO_MODE:
        return None
    raise NotImplementedError("TODO: implementar gcs_get_d1()")

# ─────────────────────────────────────────────────────────────────────────────
# ⑥ GCP – BIGQUERY
#
# TODO [COPILOT]: Descomentar código real. Instalar: pip install google-cloud-bigquery
# Service Account necesita: roles/bigquery.dataViewer
# ─────────────────────────────────────────────────────────────────────────────

def bq_get_order(order_id: str) -> dict | None:
    """Consulta estado de una orden desde BigQuery.
    TODO [COPILOT]:
        client = bq_lib.Client(project=CFG["project"])
        q = f'''SELECT order_id, status, source_file, total_documents, created_at
                FROM `{CFG["project"]}.{CFG["bq_dataset"]}.orders`
                WHERE order_id = @order_id LIMIT 1'''
        job_cfg = bq_lib.QueryJobConfig(query_parameters=[
            bq_lib.ScalarQueryParameter("order_id","STRING",order_id)])
        rows = list(client.query(q, job_config=job_cfg).result())
        if not rows: return None
        r = rows[0]
        return {"order_id":r.order_id,"status":r.status,"source_file":r.source_file,
                "total_documents":r.total_documents,"created_at":r.created_at}"""
    if DEMO_MODE: return None
    raise NotImplementedError("TODO: implementar bq_get_order()")

def bq_translations_count(order_id: str) -> int:
    """TODO [COPILOT]:
        client = bq_lib.Client(project=CFG["project"])
        q = f'''SELECT COUNT(*) as cnt
                FROM `{CFG["project"]}.{CFG["bq_dataset"]}.translations` t
                JOIN `{CFG["project"]}.{CFG["bq_dataset"]}.documents` d ON t.doc_id=d.doc_id
                WHERE d.order_id = @order_id'''
        job_cfg = bq_lib.QueryJobConfig(query_parameters=[
            bq_lib.ScalarQueryParameter("order_id","STRING",order_id)])
        return int(list(client.query(q, job_config=job_cfg).result())[0].cnt)"""
    if DEMO_MODE: return 0
    raise NotImplementedError("TODO: implementar bq_translations_count()")

def bq_get_history(limit: int = 50) -> pd.DataFrame:
    """TODO [COPILOT]:
        client = bq_lib.Client(project=CFG["project"])
        q = f'''SELECT order_id, status, source_file, total_documents, created_at
                FROM `{CFG["project"]}.{CFG["bq_dataset"]}.orders`
                ORDER BY created_at DESC LIMIT @limit'''
        job_cfg = bq_lib.QueryJobConfig(query_parameters=[
            bq_lib.ScalarQueryParameter("limit","INT64",limit)])
        return client.query(q, job_config=job_cfg).to_dataframe()"""
    if DEMO_MODE: return pd.DataFrame()
    raise NotImplementedError("TODO: implementar bq_get_history()")

# ─────────────────────────────────────────────────────────────────────────────
# ⑦ GCP – CLOUD COMPOSER (AIRFLOW)
#
# DOS OPCIONES para disparar el pipeline:
#
# OPCIÓN A – TRIGGER MANUAL via Composer API (activo por defecto):
#   La UI llama a la API REST de Composer tras subir el D0.
#   Requiere AIRFLOW_URL + autenticación IAP.
#
# OPCIÓN B – GCS EVENT TRIGGER (recomendado para producción):
#   Un Eventarc trigger detecta el nuevo D0 en el bucket RAW y arranca
#   el DAG automáticamente. La UI solo sube el fichero, sin llamar a Airflow.
#   Para activar OPCIÓN B: comentar la llamada a composer_trigger_dag()
#   en el Tab Launch (buscar "OPCIÓN A" más abajo).
#   Setup GCP:
#     gcloud eventarc triggers create newsletter-d0-trigger \
#       --location=europe-west1 \
#       --destination-cloud-run-service=newsletter-trigger-fn \
#       --event-filters="type=google.cloud.storage.object.v1.finalized" \
#       --event-filters="bucket=newsletter-raw-{PROJECT_ID}" \
#       --event-filters-path-pattern="name=inbox/**"
# ─────────────────────────────────────────────────────────────────────────────

def composer_trigger_dag(order_id: str, gcs_path: str) -> str:
    """Dispara el DAG en Cloud Composer via API REST (OPCIÓN A).
    TODO [COPILOT]: Implementar con IAP token.
    Pasos:
        1. Obtener IAP token para autenticar contra Composer:
           import google.auth.transport.requests, google.oauth2.id_token
           iap_client_id = os.getenv("COMPOSER_IAP_CLIENT_ID")
           req = google.auth.transport.requests.Request()
           iap_token = google.oauth2.id_token.fetch_id_token(req, iap_client_id)
        2. POST al endpoint de Composer:
           import requests as req_lib
           dag_run_id = f"ui__{order_id}__{datetime.now().strftime('%Y%m%dT%H%M%S')}"
           url = f"{CFG['airflow_url']}/api/v1/dags/{CFG['airflow_dag']}/dagRuns"
           resp = req_lib.post(url,
               json={"dag_run_id":dag_run_id, "conf":{"order_id":order_id,"gcs_path":gcs_path}},
               headers={"Authorization":f"Bearer {iap_token}"}, timeout=15)
           resp.raise_for_status()
           return dag_run_id"""
    if DEMO_MODE:
        return f"ui__{order_id}__{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    raise NotImplementedError("TODO: implementar composer_trigger_dag()")

# ─────────────────────────────────────────────────────────────────────────────
# ⑧ DEMO – simulación completa del pipeline en tiempo real
# ─────────────────────────────────────────────────────────────────────────────

def _demo_stage(launch_ts: datetime) -> int:
    elapsed = (datetime.now() - launch_ts).total_seconds()
    cum = 0
    for i, d in enumerate(DEMO_DURATIONS):
        cum += d
        if elapsed < cum: return i
    return len(DEMO_DURATIONS) - 1

def _demo_order(order_id, launch_ts, filename, n_docs):
    stage = _demo_stage(launch_ts)
    statuses = ["pending","processing","ingested","translated","completed"]
    return {"order_id":order_id, "status":statuses[min(stage,4)],
            "source_file":filename, "total_documents":n_docs, "created_at":launch_ts}

def _demo_translations(n_docs, stage):
    if stage < 2: return 0
    if stage == 2: return n_docs * random.randint(1, 4)
    return n_docs * len(TARGET_LANGS)

def _demo_d1_bytes(order_id, n_docs=8):
    rows = []
    topics = ["ESG","ECO_OUTLOOK","FIXED_INCOME","EQUITIES"]
    for i in range(n_docs):
        for lang in TARGET_LANGS:
            rows.append({"_DOCUMENT":f"{topics[i%4]}{lang}_{i+1:03d}","ID_LANG":lang,
                "RANK":0.5,"ID_TOPIC":topics[i%4],
                "TITLE":f"[{LANG_NAMES[lang]}] Demo title {i+1}",
                "SUMMARY":f"[{LANG_NAMES[lang]}] Demo summary {i+1}.",
                "APPROVED":0,"IS_ALIAS":False,
                "DATE_COMPUTATION":datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    buf = BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()

def _demo_history():
    now = datetime.now()
    statuses = ["completed","completed","completed","translated","error","completed"]
    return pd.DataFrame([{
        "order_id":str(uuid.uuid4())[:8].upper(), "status":s,
        "source_file":f"D0_week_{i+1}.xlsx", "total_documents":random.randint(5,15),
        "created_at":now-timedelta(days=i*2,hours=random.randint(0,12)),
        "duration":f"{random.randint(1,6)}m {random.randint(10,59)}s",
    } for i,s in enumerate(statuses)])

# ─────────────────────────────────────────────────────────────────────────────
# ⑨ COMPONENTES UI
# ─────────────────────────────────────────────────────────────────────────────

def _pill(status):
    return f'<span class="pill-{status}">{status}</span>'

def _badge(demo, T):
    k = "demo_badge" if demo else "real_badge"
    c = "badge-demo" if demo else "badge-real"
    return f'<span class="{c}">{T[k]}</span>'

def _elapsed(created_at):
    if not created_at: return "—"
    ts = created_at
    if isinstance(ts, str): ts = datetime.fromisoformat(ts)
    if hasattr(ts,"tzinfo") and ts.tzinfo: ts = ts.replace(tzinfo=None)
    m, s = divmod(int((datetime.now()-ts).total_seconds()), 60)
    return f"{m}m {s}s"

def _card(label, value, sub=""):
    sub_html = f'<div class="card-sub">{sub}</div>' if sub else ""
    return (f'<div class="info-card"><div class="card-label">{label}</div>'
            f'<div class="card-value">{value}</div>{sub_html}</div>')

def _render_pipeline(stage_idx, lang):
    cols = st.columns(len(PIPELINE_STAGES))
    for i, (col, stage) in enumerate(zip(cols, PIPELINE_STAGES)):
        with col:
            state = ("done" if i < stage_idx
                     else ("active" if i == stage_idx else "wait"))
            if stage_idx == -1: state = "error" if i == 0 else "done"
            lbl = stage["es"] if lang == "ES" else stage["en"]
            icon_style = "filter:brightness(10)" if state == "active" else ""
            st.markdown(f"""
            <div style="text-align:center;padding:.5rem 0">
                <div class="stage-icon {state}">
                    <span style="{icon_style}">{stage["icon"]}</span>
                </div>
                <div class="stage-lbl {state}" style="margin-top:.4rem">{lbl}</div>
                <div class="stage-svc">{stage["service"]}</div>
            </div>""", unsafe_allow_html=True)
            if i < len(PIPELINE_STAGES)-1:
                color = ("#0066B3" if i < stage_idx else
                         ("linear-gradient(90deg,#0066B3 50%,#DDE3EC 100%)" if i == stage_idx
                          else "#DDE3EC"))
                st.markdown(f'<div style="height:2px;background:{color};'
                            f'margin:-2.6rem 0 0 50%;width:calc(50% + 1px)"></div>',
                            unsafe_allow_html=True)

def _render_logs(order_id, stage_idx):
    now = datetime.now().strftime("%H:%M:%S")
    logs = []
    if stage_idx >= 0:
        logs += [f'<span class="log-info">[{now}] DAG triggered · order_id={order_id}</span>',
                 f'<span class="log-info">[{now}] SFTPToGCSOperator · uploading D0...</span>']
    if stage_idx >= 1:
        logs += [f'<span class="log-ok">[{now}] GCS upload complete ✓</span>',
                 f'<span class="log-info">[{now}] Cloud Run ingestion-service · POST /process</span>']
    if stage_idx >= 2:
        logs += [f'<span class="log-ok">[{now}] Ingestion complete · documents in BigQuery ✓</span>',
                 f'<span class="log-info">[{now}] Cloud Run translation-service · POST /translate/{order_id}</span>',
                 f'<span class="log-info">[{now}] Vertex AI Gemini · translating to {len(TARGET_LANGS)} langs...</span>']
    if stage_idx >= 3:
        logs += [f'<span class="log-ok">[{now}] Translations complete · BigQuery rows written ✓</span>',
                 f'<span class="log-info">[{now}] Cloud Run generation-service · POST /generate/{order_id}</span>']
    if stage_idx >= 4:
        logs += [f'<span class="log-ok">[{now}] D1 generated · gs://.../output/{order_id}/D1-{order_id}.xlsx ✓</span>',
                 f'<span class="log-ok">[{now}] Pipeline completed ✓</span>']
    if not logs:
        logs = [f'<span class="log-info">Waiting for pipeline to start...</span>']
    st.markdown(f'<div class="log-terminal">{"<br>".join(logs)}</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# ⑩ APP PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Smart Newsletter · Ops", page_icon="📡",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

user = require_auth()

for k, v in {"order_id":None,"gcs_path":None,"dag_run_id":None,"launch_ts":None,"n_docs":0}.items():
    if k not in st.session_state: st.session_state[k] = v

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    ui_lang = st.radio("🌐 Interface / Interfaz", ["ES","EN"], horizontal=True)
    T = TEXTS[ui_lang]
    st.markdown("---")
    st.markdown(_badge(DEMO_MODE, T), unsafe_allow_html=True)
    st.markdown("")
    if DEMO_MODE:
        st.markdown("**GCP Project:** `smart-newsletter-dev`")
        st.markdown("**Bucket RAW:** `newsletter-raw-dev`")
        st.markdown("**Airflow:** `composer-demo...`")
        st.caption("Configura variables de entorno para conectar a GCP.")
    else:
        st.markdown(f"**GCP Project:** `{CFG['project']}`")
        st.markdown(f"**Bucket RAW:** `{CFG['bucket_raw']}`")
        st.markdown(f"**Airflow:** `{CFG['airflow_url'][:35]}...`")
    if user:
        st.markdown("---")
        st.caption(f"👤 {user.get('name', user.get('email',''))}")
        if st.button("Cerrar sesión", use_container_width=True):
            logout()
    st.markdown("---")
    st.markdown("**Pipeline:**")
    for s in PIPELINE_STAGES:
        lbl = s["es"] if ui_lang == "ES" else s["en"]
        st.caption(f"{s['icon']} {lbl} — {s['service']}")

# ── Header ─────────────────────────────────────────────────────────────────
# TODO [COPILOT]: reemplazar <div class="logo-box">DB</div> por
#   <img src="assets/db_logo.svg" height="40" alt="Deutsche Bank">
#   cuando el asset esté disponible en el repositorio
st.markdown(f"""
<div class="ops-header">
    <div class="logo-box">DB</div>
    <div>
        <p class="hdr-title">Smart Newsletter · Pipeline Ops</p>
        <p class="hdr-sub">GCS → Cloud Composer → Cloud Run → Vertex AI → BigQuery</p>
    </div>
    <div style="margin-left:auto">{_badge(DEMO_MODE, T)}</div>
</div>""", unsafe_allow_html=True)

# ── Tabs ───────────────────────────────────────────────────────────────────
tab_launch, tab_monitor, tab_history = st.tabs([T["tab_launch"],T["tab_monitor"],T["tab_history"]])

# ═══════════════════════════════════════════
# TAB LAUNCH
# ═══════════════════════════════════════════
with tab_launch:
    st.markdown(f'<p class="sec-title">{T["launch_title"]}</p>', unsafe_allow_html=True)
    if DEMO_MODE:
        st.warning(T["demo_warn"])

    uploaded = st.file_uploader(T["upload_label"], type=["xlsx","xls"], help=T["upload_hint"])

    if uploaded:
        try:
            df_raw = pd.read_excel(uploaded)
        except Exception as e:
            st.error(f"Error leyendo el fichero: {e}")
            df_raw = None

        if df_raw is not None:
            missing = [c for c in D0_REQUIRED if c not in df_raw.columns]
            if missing:
                st.error(f"{T['file_err']} `{'`, `'.join(missing)}`")
            else:
                lang_counts  = df_raw["LANGUAGE"].value_counts().to_dict() if "LANGUAGE" in df_raw.columns else {}
                topic_counts = df_raw["TOPIC"].value_counts().to_dict()    if "TOPIC" in df_raw.columns else {}
                st.success(f"{T['file_ok']} · **{len(df_raw)} {T['file_docs']}** · {len(df_raw.columns)} {T['file_cols']}")

                c1, c2, c3 = st.columns(3)
                with c1: st.markdown(_card("Documents", len(df_raw), f"D1 rows → {len(df_raw)*len(TARGET_LANGS)}"), unsafe_allow_html=True)
                with c2: st.markdown(_card("Source Languages", len(lang_counts), ", ".join(lang_counts.keys())), unsafe_allow_html=True)
                with c3: st.markdown(_card("Topics", len(topic_counts), ", ".join(list(topic_counts.keys())[:3])), unsafe_allow_html=True)

                st.markdown("")
                with st.expander("Preview D0", expanded=False):
                    st.dataframe(df_raw.head(5), use_container_width=True, hide_index=True)

                st.markdown("")
                if st.button(T["btn_launch"], type="primary", use_container_width=True):
                    with st.spinner(T["launching"]):
                        file_bytes = uploaded.getvalue()
                        filename   = uploaded.name
                        if DEMO_MODE:
                            time.sleep(1.2)
                            order_id   = str(uuid.uuid4())[:8].upper()
                            gcs_path   = f"gs://newsletter-raw-demo/inbox/{order_id}/{filename}"
                            dag_run_id = f"ui__{order_id}__{datetime.now().strftime('%Y%m%dT%H%M%S')}"
                        else:
                            order_id   = str(uuid.uuid4())[:8].upper()
                            gcs_path   = gcs_upload_d0(file_bytes, filename, order_id)
                            # OPCIÓN A: trigger manual via Composer API
                            dag_run_id = composer_trigger_dag(order_id, gcs_path)
                            # OPCIÓN B (GCS Event Trigger): comentar línea anterior y usar:
                            # dag_run_id = f"auto__{order_id}"

                    st.session_state.update({"order_id":order_id,"gcs_path":gcs_path,
                        "dag_run_id":dag_run_id,"launch_ts":datetime.now(),"n_docs":len(df_raw)})
                    st.success(T["launched_ok"])
                    st.markdown(f"""
                    <div class="order-display">
                        <div class="oid-lbl">{T['order_label']}</div>
                        <div class="oid-val">{order_id}</div>
                        <div class="oid-meta">{T['gcs_label']}: {gcs_path}<br>{T['dag_label']}: {dag_run_id}</div>
                    </div>""", unsafe_allow_html=True)
                    st.info(T["go_monitor"])
    elif st.session_state["order_id"]:
        st.info(f"Pipeline activo: `{st.session_state['order_id']}` → **{T['tab_monitor']}**")

# ═══════════════════════════════════════════
# TAB MONITOR
# ═══════════════════════════════════════════
with tab_monitor:
    st.markdown(f'<p class="sec-title">{T["monitor_title"]}</p>', unsafe_allow_html=True)

    col_inp, col_btn, col_auto = st.columns([3,1,1])
    with col_inp:
        monitor_id = st.text_input(T["order_input"], value=st.session_state.get("order_id") or "",
                                   label_visibility="collapsed", placeholder=T["order_input"])
    with col_btn:
        st.button(T["btn_refresh"])
    with col_auto:
        auto_refresh = st.checkbox(T["autorefresh"], value=bool(st.session_state.get("order_id")))

    if not monitor_id:
        st.info(T["no_order"])
    else:
        if DEMO_MODE:
            launch_ts = st.session_state.get("launch_ts")
            n_docs    = st.session_state.get("n_docs", 8)
            order = (_demo_order(monitor_id, launch_ts, "D0.xlsx", n_docs) if launch_ts
                     else {"order_id":monitor_id,"status":"translated","source_file":"D0_dummy.xlsx",
                           "total_documents":8,"created_at":datetime.now()-timedelta(minutes=3)})
        else:
            order = bq_get_order(monitor_id)

        if not order:
            st.warning(f"Order `{monitor_id}` no encontrado en BigQuery.")
        else:
            status    = order["status"]
            stage_idx = STATUS_TO_STAGE.get(status, 0)
            n_docs    = order.get("total_documents", 0)

            c1,c2,c3,c4 = st.columns(4)
            with c1: st.markdown(_card("Order ID", f'<span style="font-size:.9rem;font-family:var(--mono)">{order["order_id"]}</span>'), unsafe_allow_html=True)
            with c2: st.markdown(_card("Status", _pill(status)), unsafe_allow_html=True)
            with c3: st.markdown(_card(T["docs_label"], n_docs), unsafe_allow_html=True)
            with c4: st.markdown(_card(T["elapsed"], _elapsed(order.get("created_at"))), unsafe_allow_html=True)

            st.markdown("")
            _render_pipeline(stage_idx, ui_lang)
            st.markdown("")

            if stage_idx >= 2:
                n_trans = (_demo_translations(n_docs, stage_idx) if DEMO_MODE
                           else bq_translations_count(monitor_id))
                st.markdown(_card(T["trans_label"], n_trans, f"{n_docs} docs × {len(TARGET_LANGS)} langs"),
                            unsafe_allow_html=True)
                st.markdown("")

            st.markdown(f'<p class="sec-title">{T["bq_logs"]}</p>', unsafe_allow_html=True)
            _render_logs(monitor_id, stage_idx)

            if status == "completed":
                st.markdown("")
                st.success(T["d1_ready"])
                if DEMO_MODE:
                    st.download_button(label=T["btn_download"],
                        data=_demo_d1_bytes(monitor_id, n_docs),
                        file_name=f"D1-{monitor_id}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary", use_container_width=True)
                else:
                    d1 = gcs_get_d1(monitor_id)
                    if isinstance(d1, str):
                        st.link_button(T["btn_download"], d1, use_container_width=True)
                    elif isinstance(d1, bytes):
                        st.download_button(T["btn_download"], data=d1,
                            file_name=f"D1-{monitor_id}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary", use_container_width=True)
                    else:
                        st.error("D1 no disponible todavía en GCS.")

            if auto_refresh and status not in ("completed","error"):
                time.sleep(5)
                st.rerun()

# ═══════════════════════════════════════════
# TAB HISTORY
# ═══════════════════════════════════════════
with tab_history:
    st.markdown(f'<p class="sec-title">{T["history_title"]}</p>', unsafe_allow_html=True)
    if DEMO_MODE:
        df_hist = _demo_history()
    else:
        try:
            df_hist = bq_get_history()
        except Exception as e:
            st.error(f"Error BigQuery: {e}")
            df_hist = pd.DataFrame()

    if df_hist.empty:
        st.info(T["history_empty"])
    else:
        col_map = {"order_id":T["col_order"],"status":T["col_status"],"source_file":T["col_file"],
                   "total_documents":T["col_docs"],"created_at":T["col_date"],"duration":T["col_dur"]}
        st.dataframe(
            df_hist.rename(columns={k:v for k,v in col_map.items() if k in df_hist.columns}),
            use_container_width=True, hide_index=True,
            column_config={
                T["col_date"]: st.column_config.DatetimeColumn(T["col_date"]),
                T["col_docs"]: st.column_config.NumberColumn(T["col_docs"]),
            })

# ── Footer ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<p class="footer-bar">Deutsche Bank · Smart Newsletter · Pipeline Ops · v0.2.0 · '
            'GCS → Cloud Composer → Cloud Run → Vertex AI → BigQuery · Auth: ForgeRock OIDC (prod)</p>',
            unsafe_allow_html=True)
