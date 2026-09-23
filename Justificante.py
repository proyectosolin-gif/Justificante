import base64
import io
import urllib
from datetime import datetime, timedelta, timezone
import pandas as pd
import pyodbc
import qrcode
from sqlalchemy import create_engine, text
import streamlit as st

# ------------------------------------------------------------------
# 1. Configuración de página
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Gestión de Justificantes - Orientación Educativa",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------
# Estilos CSS Personalizados
# ------------------------------------------------------------------
st.markdown(
    """
    <style>
    footer {visibility: hidden;}
    
    .card-gestor {
        padding: 12px;
        border-radius: 8px;
        background-color: #E0F2FE;
        border: 1px solid #7DD3FC;
        color: #0C4A6E;
        font-weight: 600;
        margin-bottom: 15px;
    }
    
    .tag-justificado {
        background-color: #DEF7EC;
        color: #03543F;
        font-weight: bold;
        padding: 3px 8px;
        border-radius: 4px;
        border: 1px solid #84E1BC;
        font-size: 0.85rem;
    }

    .ticket-comprobante {
        border: 2px dashed #9CA3AF;
        padding: 20px;
        border-radius: 10px;
        background-color: #FAFAFA;
        text-align: center;
        margin-top: 15px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------
# Configuración y Funciones de Conexión
# ------------------------------------------------------------------
@st.cache_resource
def obtener_conexion():
    drivers_instalados = pyodbc.drivers()
    driver_elegido = "SQL Server"
    for d in [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]:
        if d in drivers_instalados:
            driver_elegido = d
            break

    try:
        server = st.secrets["db_credentials"]["SERVER"]
        database = st.secrets["db_credentials"]["DATABASE"]
        username = st.secrets["db_credentials"]["UID"]
        password = st.secrets["db_credentials"]["PWD"]
    except Exception:
        server = "CBTis139.mssql.somee.com"
        database = "CBTis139"
        username = "TovarLara_SQLLogin_1"
        password = "1hmetvyyiv"

    connection_string = (
        f"DRIVER={{{driver_elegido}}};SERVER={server};DATABASE={database};"
        f"UID={username};PWD={password};TrustServerCertificate=yes;"
    )
    params = urllib.parse.quote_plus(connection_string)
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")


def cerrar_sesion():
    st.session_state.clear()
    st.rerun()


def generar_qr_bytes(contenido: str) -> bytes:
    """Genera la imagen QR en memoria y retorna sus bytes PNG."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(contenido)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


# Función para limpiar el comprobante al cambiar de selección
def limpiar_comprobante_previo():
    st.session_state["comprobante_reciente"] = None


engine = obtener_conexion()

# Inicializar Estados de Sesión
if "autenticado_orientacion" not in st.session_state:
    st.session_state["autenticado_orientacion"] = False
    st.session_state["idgestor"] = None
    st.session_state["nombre_gestor"] = ""

if "comprobante_reciente" not in st.session_state:
    st.session_state["comprobante_reciente"] = None

# ------------------------------------------------------------------
# 2. PANTALLA DE ACCESO Y AUTENTICACIÓN
# ------------------------------------------------------------------
if not st.session_state["autenticado_orientacion"]:
    st.title("📋 Control de Justificantes Escolares")
    st.subheader("🔐 Orientación Educativa - Validación de Responsable")

    col_login, _ = st.columns([1, 2])
    with col_login:
        with st.form("form_login_gestor"):
            password_input = st.text_input(
                "🔑 Contraseña de Gestor:", type="password", key="input_pass_gestor"
            )
            btn_login = st.form_submit_button(
                "🔓 Validar Contraseña", type="primary", use_container_width=True
            )

            if btn_login:
                pwd_clean = password_input.strip()
                if not pwd_clean:
                    st.warning("⚠️ Por favor ingrese su contraseña.")
                else:
                    try:
                        query_gestor = text("""
                            SELECT 
                                LTRIM(RTRIM(idgestor)) AS idgestor, 
                                LTRIM(RTRIM(nombre)) AS nombre,
                                puesto,
                                activo
                            FROM Gestor 
                            WHERE LTRIM(RTRIM(password)) = :pwd 
                              AND activo = 3
                        """)
                        with engine.connect() as conn:
                            res = conn.execute(query_gestor, {"pwd": pwd_clean}).fetchone()
                            if res:
                                st.session_state["autenticado_orientacion"] = True
                                st.session_state["idgestor"] = res.idgestor
                                st.session_state["nombre_gestor"] = res.nombre
                                st.success(f"✅ Bienvenido(a): {res.nombre}")
                                st.rerun()
                            else:
                                st.error(
                                    "❌ Acceso denegado: Contraseña incorrecta o el gestor "
                                    "no cuenta con el estatus/perfil requerido (activo = 3)."
                                )
                    except Exception as err_log:
                        st.error(f"⚠️ Error al conectar a la base de datos: {err_log}")
    st.stop()

# ------------------------------------------------------------------
# 3. BARRA LATERAL (INFORMACIÓN DEL RESPONSABLE)
# ------------------------------------------------------------------
st.sidebar.title("📌 Orientación Educativa")
st.sidebar.markdown(
    f"""
    <div class="card-gestor">
        👤 <b>Responsable Autorizado:</b><br>
        {st.session_state['nombre_gestor']}<br>
        <small>ID Gestor: {st.session_state['idgestor']}</small>
    </div>
""",
    unsafe_allow_html=True,
)

if st.sidebar.button("🔒 Cerrar Sesión", use_container_width=True):
    cerrar_sesion()

# ------------------------------------------------------------------
# 4. MÓDULO PRINCIPAL DE JUSTIFICANTES
# ------------------------------------------------------------------
st.title("📑 Módulo de Emisión y Registro de Justificantes")
st.caption("Seleccione el grupo y alumno para consultar las inasistencias y aplicar la justificación correspondiente.")

try:
    # 4.1 Cargar Lista de Grupos
    query_grupos = text("SELECT DISTINCT LTRIM(RTRIM(grupo)) AS grupo FROM Alumno ORDER BY grupo")
    with engine.connect() as conn:
        df_grupos = pd.read_sql(query_grupos, conn)

    if df_grupos.empty:
        st.warning("⚠️ No se encontraron grupos registrados en la tabla Alumno.")
        st.stop()

    col_grp, col_alm = st.columns([1, 2])
    
    with col_grp:
        # Al cambiar de grupo se limpia el comprobante activo
        grupo_sel = st.selectbox(
            "🏫 Seleccionar Grupo:", 
            df_grupos["grupo"].tolist(),
            on_change=limpiar_comprobante_previo
        )

    # 4.2 Cargar Alumnos del Grupo Seleccionado
    query_alumnos = text("""
        SELECT LTRIM(RTRIM(idalumno)) AS idalumno, LTRIM(RTRIM(nombre)) AS nombre 
        FROM Alumno 
        WHERE LTRIM(RTRIM(grupo)) = :grp 
        ORDER BY nombre
    """)
    with engine.connect() as conn:
        df_alumnos = pd.read_sql(query_alumnos, conn, params={"grp": grupo_sel})

    with col_alm:
        if not df_alumnos.empty:
            dict_alumnos = {
                f"{row['nombre']} (ID: {row['idalumno']})": (row["idalumno"], row["nombre"])
                for _, row in df_alumnos.iterrows()
            }
            # Al cambiar de alumno se limpia el comprobante activo
            alumno_lbl_sel = st.selectbox(
                "👤 Seleccionar Alumno:", 
                list(dict_alumnos.keys()),
                on_change=limpiar_comprobante_previo
            )
            id_alumno_sel, nombre_alumno_sel = dict_alumnos[alumno_lbl_sel]
        else:
            st.info("ℹ️ No hay alumnos registrados en este grupo.")
            st.stop()

    st.divider()

    # ------------------------------------------------------------------
    # MOSTRAR COMPROBANTE DIGITAL SI ACABA DE GENERARSE
    # ------------------------------------------------------------------
    if st.session_state["comprobante_reciente"] is not None:
        comp = st.session_state["comprobante_reciente"]
        st.success("🎉 ¡Justificante procesado con éxito en el sistema!")

        with st.expander("📄 **COMPROBANTE DIGITAL Y CÓDIGO QR GENERADO**", expanded=True):
            col_info, col_qr = st.columns([2, 1])

            with col_info:
                st.markdown(f"### 🏫 **Orientación Educativa - CBTis 139**")
                st.markdown(f"**Fecha y Hora:** {comp['fecha_emision']}")
                st.markdown(f"**Alumno:** {comp['alumno']} (ID: `{comp['id_alumno']}`)")
                st.markdown(f"**Grupo:** `{comp['grupo']}`")
                st.markdown(f"**Atendió (Gestor):** {comp['gestor']}")
                st.markdown(f"**Faltas Justificadas:** {comp['total_faltas']} registro(s)")
                st.markdown(f"**Motivo Registrado:** *{comp['motivo']}*")
                st.caption("📱 *El alumno puede escanear o tomar foto directa a este comprobante desde la pantalla.*")

            with col_qr:
                qr_bytes = generar_qr_bytes(comp["texto_qr"])
                st.image(qr_bytes, caption="Comprobante Digital QR", width=200)

                st.download_button(
                    label="💾 Descargar QR (PNG)",
                    data=qr_bytes,
                    file_name=f"Justificante_{comp['id_alumno']}_{datetime.now().strftime('%Y%m%d%H%M')}.png",
                    mime="image/png",
                    use_container_width=True,
                )

            if st.button("❌ Cerrar Comprobante", use_container_width=False):
                st.session_state["comprobante_reciente"] = None
                st.rerun()

        st.divider()

    # 4.3 Consultar historial completo con CAST en campos TEXT/NTEXT
    query_faltas = text("""
        SELECT DISTINCT
            a.idasistencia,
            CONVERT(VARCHAR(10), a.fecha, 103) AS fecha_formato,
            a.fecha,
            a.hora,
            a.idhorario,
            a.estado,
            ISNULL(CAST(a.motivo AS VARCHAR(MAX)), '') AS motivo,
            ISNULL(CAST(m.nombre AS VARCHAR(MAX)), 'Materia no especificada') AS materia
        FROM Asistencia a
        LEFT JOIN Horario_Grupo h ON LTRIM(RTRIM(CAST(a.idhorario AS VARCHAR(50)))) = LTRIM(RTRIM(CAST(h.idhorario AS VARCHAR(50))))
        LEFT JOIN materia m ON h.idmateria = m.idmateria
        WHERE LTRIM(RTRIM(CAST(a.idalumno AS VARCHAR(50)))) = :id_al
        ORDER BY a.fecha DESC, a.hora DESC
    """)

    with engine.connect() as conn:
        df_faltas = pd.read_sql(query_faltas, conn, params={"id_al": id_alumno_sel})

    if df_faltas.empty:
        st.success("🎉 El alumno seleccionado no tiene registros de inasistencias en la base de datos.")
    else:
        st.subheader("📋 Registro e Historial de Inasistencias")
        st.caption("Los registros marcados en verde ya cuentan con justificante y no se pueden volver a seleccionar.")

        with st.form("form_aplicar_justificante"):
            seleccionados = []

            # Encabezado de la tabla
            c_chk, c_fec, c_hor, c_mat, c_idh, c_est = st.columns([1, 2, 1.5, 3.5, 1.5, 2])
            c_chk.markdown("**Seleccionar**")
            c_fec.markdown("**Fecha**")
            c_hor.markdown("**Hora**")
            c_mat.markdown("**Materia**")
            c_idh.markdown("**ID Horario**")
            c_est.markdown("**Estatus**")
            st.divider()

            for idx, row in df_faltas.iterrows():
                id_asist = row["idasistencia"]
                es_justificado = (int(row["estado"]) == 4)
                
                c_chk, c_fec, c_hor, c_mat, c_idh, c_est = st.columns([1, 2, 1.5, 3.5, 1.5, 2])
                
                if es_justificado:
                    c_chk.checkbox("", value=True, disabled=True, key=f"chk_asist_{id_asist}_{idx}")
                    c_fec.markdown(f"<span style='color: #03543F; font-weight: 600;'>{row['fecha_formato']}</span>", unsafe_allow_html=True)
                    c_hor.markdown(f"<span style='color: #03543F; font-weight: 600;'>{str(row['hora'])[:5]}</span>", unsafe_allow_html=True)
                    
                    materia_texto = f"**{row['materia']}**"
                    if row["motivo"]:
                        materia_texto += f"<br><small style='color: #4B5563;'><i>Motivo: {row['motivo']}</i></small>"
                    c_mat.markdown(materia_texto, unsafe_allow_html=True)
                    
                    c_idh.markdown(f"<span style='color: #03543F;'>{row['idhorario']}</span>", unsafe_allow_html=True)
                    c_est.markdown("<span class='tag-justificado'>✅ JUSTIFICADO</span>", unsafe_allow_html=True)
                else:
                    check_val = c_chk.checkbox("", disabled=False, key=f"chk_asist_{id_asist}_{idx}")
                    if check_val:
                        seleccionados.append(id_asist)

                    c_fec.write(row["fecha_formato"])
                    c_hor.write(str(row["hora"])[:5])
                    c_mat.write(row["materia"])
                    c_idh.write(str(row["idhorario"]))
                    c_est.write("❌ Falta Pendiente")

                st.markdown("<hr style='margin: 4px 0px; border-color: #F3F4F6;'>", unsafe_allow_html=True)

            st.divider()

            # 4.4 Captura del Motivo
            st.markdown("### 📝 Redacción del Motivo de Justificación")
            motivo_input = st.text_area(
                "Escriba la razón de la falta (Ej. Cita médica, asunto familiar, etc.):",
                height=100,
                placeholder="Escriba aquí el motivo detallado...",
            )

            btn_guardar_justificante = st.form_submit_button(
                "📋 Aplicar Justificación y Generar Comprobante QR",
                type="primary",
                use_container_width=True,
            )

            if btn_guardar_justificante:
                motivo_clean = motivo_input.strip()
                
                if not seleccionados:
                    st.warning("⚠️ Debe seleccionar al menos una falta pendiente de la lista superior.")
                elif not motivo_clean:
                    st.warning("⚠️ Por favor redáctese el motivo de la falta antes de guardar.")
                else:
                    try:
                        ids_unicos = list(set(seleccionados))
                        
                        query_update = text("""
                            UPDATE Asistencia 
                            SET estado = 4, motivo = :motivo
                            WHERE idasistencia = :id_asist
                        """)
                        
                        with engine.begin() as conn:
                            for id_asist in ids_unicos:
                                conn.execute(
                                    query_update,
                                    {"motivo": motivo_clean, "id_asist": id_asist},
                                )

                        # Construir datos para el comprobante
                        fecha_hoy_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        texto_qr_validar = (
                            f"COMPROBANTE DE JUSTIFICANTE\n"
                            f"Fecha Emision: {fecha_hoy_str}\n"
                            f"Alumno: {nombre_alumno_sel} ({id_alumno_sel})\n"
                            f"Grupo: {grupo_sel}\n"
                            f"Faltas Justificadas: {len(ids_unicos)}\n"
                            f"IDs Asistencia: {', '.join(map(str, ids_unicos))}\n"
                            f"Gestor: {st.session_state['nombre_gestor']}\n"
                            f"Motivo: {motivo_clean}"
                        )

                        st.session_state["comprobante_reciente"] = {
                            "fecha_emision": fecha_hoy_str,
                            "alumno": nombre_alumno_sel,
                            "id_alumno": id_alumno_sel,
                            "grupo": grupo_sel,
                            "gestor": st.session_state["nombre_gestor"],
                            "total_faltas": len(ids_unicos),
                            "motivo": motivo_clean,
                            "texto_qr": texto_qr_validar,
                        }

                        st.balloons()
                        st.rerun()

                    except Exception as err_upd:
                        st.error(f"❌ Error al actualizar la base de datos: {err_upd}")

except Exception as err_gen:
    st.error(f"⚠️ Ocurrió un problema al cargar el módulo: {err_gen}")