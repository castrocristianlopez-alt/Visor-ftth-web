import os
import tempfile
import zipfile

import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import pyogrio

# ==============================================================================
# CONFIGURACIÓN PÁGINA Y ESTILOS
# ==============================================================================
st.set_page_config(page_title="Gestor WebGIS FTTH", layout="wide")

st.markdown("<h2 style='text-align: center; color: #1e88e5;'>🌐 GESTOR WEBGIS DE RED DE FIBRA ÓPTICA (FTTH)</h2>", unsafe_allow_html=True)

# ==============================================================================
# CARGA DIRECTA Y RÁPIDA DESDE GEOPACKAGE
# ==============================================================================
@st.cache_data(ttl=600)
def cargar_postacion():
    RUTA_CARPETA = r"C:\Users\KRIS\Desktop\Mi_WebGIS_FTTH\capas"
    NOMBRE_ARCHIVO = "huala.gpkg"
    path_completo = os.path.join(RUTA_CARPETA, NOMBRE_ARCHIVO)
    
    try:
        if not os.path.exists(path_completo):
            return None, f"No se encontró el archivo en: {path_completo}"

        gdf = gpd.read_file(path_completo, engine="pyogrio")
        
        if gdf.empty:
            return None, "El archivo GeoPackage está vacío."

        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326", allow_override=True)
        elif gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs(epsg=4326)

        gdf.columns = [str(c).lower() for c in gdf.columns]

        gdf_puntos = gdf.copy()
        if gdf_puntos.geometry.type.isin(['Point']).all():
            gdf_puntos['lon'] = gdf_puntos.geometry.x
            gdf_puntos['lat'] = gdf_puntos.geometry.y
        else:
            centroid = gdf_puntos.geometry.centroid
            gdf_puntos['lon'] = centroid.x
            gdf_puntos['lat'] = centroid.y

        return gdf_puntos, f"Cargado exitosamente: {NOMBRE_ARCHIVO}"

    except Exception as e:
        return None, f"Error al cargar el archivo GeoPackage: {str(e)}"

def procesar_archivo_subido(uploaded_file):
    """Procesa el archivo cargado mediante el explorador (KML, KMZ, GeoJSON, SHP en ZIP, GPKG)."""
    try:
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = os.path.join(tmpdir, uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            if ext == '.kmz':
                with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
                
                kml_files = []
                for root, _, files in os.walk(tmpdir):
                    for f in files:
                        if f.lower().endswith('.kml'):
                            kml_files.append(os.path.join(root, f))
                
                if not kml_files:
                    return None, "No se encontró ningún archivo .kml dentro del KMZ."
                ruta_lectura = kml_files[0]

            elif ext == '.zip':
                with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
                
                shp_files = []
                for root, _, files in os.walk(tmpdir):
                    for f in files:
                        if f.lower().endswith('.shp'):
                            shp_files.append(os.path.join(root, f))
                
                if not shp_files:
                    return None, "No se encontró ningún archivo .shp en el ZIP."
                ruta_lectura = shp_files[0]
            else:
                ruta_lectura = temp_path

            # Extraer capas con pyogrio
            try:
                capas_info = pyogrio.list_layers(ruta_lectura)
                gdfs = []
                for item in capas_info:
                    capa_nombre = item[0] if isinstance(item, (tuple, list)) else item
                    try:
                        gdf_sub = gpd.read_file(ruta_lectura, layer=capa_nombre, engine="pyogrio")
                        if not gdf_sub.empty:
                            gdfs.append(gdf_sub)
                    except Exception:
                        continue
                
                if gdfs:
                    gdf = pd.concat(gdfs, ignore_index=True)
                else:
                    gdf = gpd.read_file(ruta_lectura, engine="pyogrio")
            except Exception:
                gdf = gpd.read_file(ruta_lectura, engine="pyogrio")

        if gdf.empty:
            return None, "El archivo está vacío o no contiene geometrías."

        gdf = gdf[gdf.geometry.notnull()].copy()
        if gdf.empty:
            return None, "El archivo no contiene geometrías válidas."

        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326", allow_override=True)
        elif gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs(epsg=4326)

        gdf.columns = [str(c).lower() for c in gdf.columns]
        
        if 'geometry' in gdf.columns:
            if gdf.geometry.type.isin(['Point']).all():
                gdf['lon'] = gdf.geometry.x
                gdf['lat'] = gdf.geometry.y
            else:
                centroid = gdf.geometry.centroid
                gdf['lon'] = centroid.x
                gdf['lat'] = centroid.y

        return gdf, "OK"

    except Exception as e:
        return None, f"Error al procesar archivo: {str(e)}"

# Cargar capa base GeoPackage
gdf_postes_base, ruta_o_err = cargar_postacion()

if gdf_postes_base is None:
    st.warning(f"⚠️ Aviso sobre capa base: {ruta_o_err}")

# ==============================================================================
# ESTADOS DE SESIÓN
# ==============================================================================
if "coordenadas_mapa" not in st.session_state:
    c_lat = float(gdf_postes_base['lat'].mean()) if gdf_postes_base is not None else -34.9751
    c_lon = float(gdf_postes_base['lon'].mean()) if gdf_postes_base is not None else -71.8028
    st.session_state.coordenadas_mapa = {"lat": c_lat, "lon": c_lon, "zoom": 15}

if "cargar_capa" not in st.session_state:
    st.session_state.cargar_capa = True
if "elemento_seleccionado" not in st.session_state:
    st.session_state.elemento_seleccionado = None
if "capa_usuario" not in st.session_state:
    st.session_state.capa_usuario = None

# ==============================================================================
# BARRA SUPERIOR
# ==============================================================================
col_dir, col_btn_dir, col_btn_postes, col_btn_limpiar, col_btn_centrar = st.columns([2.2, 0.9, 1.1, 1.1, 1])

with col_dir:
    direccion_buscar = st.text_input("🔍 Buscar Dirección o Sector:", placeholder="Ej: Av. Libertad, Hualañé")

with col_btn_dir:
    st.write(" ")
    if st.button("📍 Ir a Lugar", use_container_width=True):
        if direccion_buscar.strip():
            try:
                geolocator = Nominatim(user_agent="visor_ftth_app")
                location = geolocator.geocode(f"{direccion_buscar}, Chile")
                if location:
                    st.session_state.coordenadas_mapa = {"lat": location.latitude, "lon": location.longitude, "zoom": 17}
                    st.session_state.cargar_capa = True
                    st.rerun()
            except Exception:
                st.error("No se pudo ubicar la dirección.")

with col_btn_postes:
    st.write(" ")
    if st.button("⚡ Cargar Sector", type="primary", use_container_width=True):
        st.session_state.cargar_capa = True
        st.rerun()

with col_btn_limpiar:
    st.write(" ")
    if st.button("🗑️ Limpiar Sector", use_container_width=True):
        st.session_state.cargar_capa = False
        st.session_state.elemento_seleccionado = None
        st.rerun()

with col_btn_centrar:
    st.write(" ")
    if st.button("🎯 Centrar", use_container_width=True):
        if gdf_postes_base is not None:
            st.session_state.coordenadas_mapa = {
                "lat": float(gdf_postes_base['lat'].mean()),
                "lon": float(gdf_postes_base['lon'].mean()),
                "zoom": 15
            }
        st.session_state.cargar_capa = True
        st.rerun()

# ==============================================================================
# BARRA LATERAL
# ==============================================================================
st.sidebar.header("⚙️ PANEL DE CONTROL")

st.sidebar.subheader("📂 Cargar Capa de Usuario")
archivo_subido = st.sidebar.file_uploader(
    "Selecciona archivo geográfico:",
    type=["geojson", "kml", "kmz", "zip", "gpkg"]
)

if archivo_subido is not None:
    gdf_cargado, msg = procesar_archivo_subido(archivo_subido)
    if gdf_cargado is not None and not gdf_cargado.empty:
        if st.session_state.capa_usuario is None or len(st.session_state.capa_usuario) != len(gdf_cargado):
            st.session_state.capa_usuario = gdf_cargado
            st.sidebar.success(f"Carga exitosa: {len(gdf_cargado)} elementos.")
            
            if 'lat' in gdf_cargado.columns and 'lon' in gdf_cargado.columns:
                st.session_state.coordenadas_mapa = {
                    "lat": float(gdf_cargado['lat'].mean()),
                    "lon": float(gdf_cargado['lon'].mean()),
                    "zoom": 15
                }
                st.rerun()
    else:
        st.sidebar.error(f"⚠️ {msg}")

st.sidebar.markdown("---")
st.sidebar.subheader("🗂️ Capas de Red")
ver_postacion_base = st.sidebar.checkbox("⚪ Capa Hualañé (GeoPackage)", value=True)
ver_capa_usuario = st.sidebar.checkbox("🟦 Capa Subida por Usuario", value=True)
ver_satelital = st.sidebar.checkbox("🛰️ Mapa Satelital (Google Hybrid)", value=True)

gdf_activo = st.session_state.capa_usuario if (st.session_state.capa_usuario is not None and ver_capa_usuario) else gdf_postes_base
col_placa = 'placa' if (gdf_activo is not None and 'placa' in gdf_activo.columns) else (gdf_activo.columns[0] if gdf_activo is not None else None)

st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Consulta por Placa / ID")
busqueda_texto = st.sidebar.text_input("Escribe N° de Placa/ID:", placeholder="Ej: 5-008942...")

if busqueda_texto.strip() and gdf_activo is not None and col_placa is not None:
    mask = gdf_activo[col_placa].astype(str).str.contains(busqueda_texto.strip(), case=False, na=False)
    coincidencias = gdf_activo[mask]
    if not coincidencias.empty:
        opciones_placa = coincidencias[col_placa].astype(str).unique().tolist()
        placa_elegida = st.sidebar.selectbox("Encontrados:", opciones_placa)
        record = gdf_activo[gdf_activo[col_placa].astype(str) == placa_elegida].iloc[0]
        st.session_state.elemento_seleccionado = record.drop('geometry', errors='ignore').to_dict()
        if 'lat' in record and 'lon' in record:
            st.session_state.coordenadas_mapa = {"lat": record['lat'], "lon": record['lon'], "zoom": 18}
        st.session_state.cargar_capa = True

# ==============================================================================
# MAPA E INTERFAZ
# ==============================================================================
col_mapa, col_info = st.columns([2.3, 1])

gdf_render_base = gpd.GeoDataFrame()
gdf_render_user = gpd.GeoDataFrame()

if st.session_state.cargar_capa:
    if ver_postacion_base and gdf_postes_base is not None:
        gdf_render_base = gdf_postes_base

    if ver_capa_usuario and st.session_state.capa_usuario is not None:
        gdf_render_user = st.session_state.capa_usuario

with col_mapa:
    cant_vis = len(gdf_render_base) + len(gdf_render_user)
    st.subheader(f"🗺️ Vista Espacial (Elementos visibles: {cant_vis})")

    if ver_satelital:
        m = folium.Map(
            location=[st.session_state.coordenadas_mapa["lat"], st.session_state.coordenadas_mapa["lon"]],
            zoom_start=st.session_state.coordenadas_mapa["zoom"],
            tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
            attr="Google Satellite Hybrid"
        )
    else:
        m = folium.Map(
            location=[st.session_state.coordenadas_mapa["lat"], st.session_state.coordenadas_mapa["lon"]],
            zoom_start=st.session_state.coordenadas_mapa["zoom"],
            tiles="OpenStreetMap"
        )

    if not gdf_render_base.empty:
        c_tool = [c for c in [col_placa, 'poste_id', 'empresa', 'material'] if c in gdf_render_base.columns]
        folium.GeoJson(
            gdf_render_base,
            name="Capa Hualañé (GPKG)",
            marker=folium.CircleMarker(radius=6, fill_color="#ff9800", color="#000000", weight=1, fill_opacity=0.9),
            tooltip=folium.GeoJsonTooltip(fields=c_tool, aliases=[f"{c.upper()}:" for c in c_tool]) if c_tool else None
        ).add_to(m)

    if not gdf_render_user.empty:
        cols_user = [c for c in gdf_render_user.columns if c not in ['geometry', 'lat', 'lon']]
        folium.GeoJson(
            gdf_render_user,
            name="Capa Usuario",
            style_function=lambda x: {'color': '#00e5ff', 'weight': 3, 'opacity': 0.8},
            marker=folium.CircleMarker(radius=6, fill_color="#00e5ff", color="#000000", weight=1, fill_opacity=0.9),
            tooltip=folium.GeoJsonTooltip(fields=cols_user[:4], aliases=[f"{c.upper()}:" for c in cols_user[:4]]) if cols_user else None
        ).add_to(m)

    map_data = st_folium(m, width="100%", height=530, returned_objects=["last_active_drawing"], key="mapa_visor_ftth")

    if map_data and map_data.get("last_active_drawing"):
        st.session_state.elemento_seleccionado = map_data["last_active_drawing"]["properties"]

with col_info:
    st.subheader("📋 Ficha Técnica")

    if st.session_state.elemento_seleccionado:
        data = st.session_state.elemento_seleccionado
        st.success("✅ Elemento Seleccionado")
        st.markdown("### 📌 Atributos")
        for k, v in data.items():
            if k not in ['geometry', 'lat', 'lon']:
                st.write(f"**{k.upper()}:** `{v}`")
    else:
        st.info("👆 Haz clic en un elemento del mapa para consultar sus datos.")

st.markdown("---")
st.subheader("📊 Resumen del Sector Visible")

if not gdf_render_base.empty or not gdf_render_user.empty:
    df_comb = pd.concat([gdf_render_base, gdf_render_user], ignore_index=True) if not gdf_render_user.empty else gdf_render_base
    cols_vis = [c for c in df_comb.columns if c not in ['geometry']]
    st.dataframe(pd.DataFrame(df_comb[cols_vis]), use_container_width=True, height=220)
else:
    st.caption("El sector está limpio. Navega por el mapa, carga un archivo local o presiona '⚡ Cargar Sector'.")