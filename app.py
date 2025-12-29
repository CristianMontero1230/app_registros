import os
import csv
import json
from datetime import datetime
from io import BytesIO
from flask import Flask, request, redirect, url_for, session, send_file, render_template_string
import pandas as pd
from openpyxl.styles import Font, PatternFill

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-dev')

ADMIN_USER = os.environ.get('ADMIN_USER')
ADMIN_PASS = os.environ.get('ADMIN_PASS')

DATA_HEADERS = [
    'ID',
    'Nombre profesional',
    'Documento profesional',
    'Nombre paciente',
    'Documento paciente',
    'Fecha inicio',
    'Municipio',
    'Procedimiento',
    'Subido a Panacea',
    'Novedad',
    'Creado',
    'Modificado'
]

DATA_ACTIVITIES_HEADERS = [
    'ID',
    'Fecha',
    'Nombre profesional',
    'Actividad',
    'Creado',
    'Modificado'
]

DATA_PATH = os.path.join(os.path.dirname(__file__), 'registros_procedimientos.csv')
DATA_ACTIVITIES_PATH = os.path.join(os.path.dirname(__file__), 'registros_actividades.csv')
EXCEL_PATH = os.path.join(os.path.dirname(__file__), 'registros_procedimientos.xlsx')
EXCEL_ACTIVITIES_PATH = os.path.join(os.path.dirname(__file__), 'registros_actividades.xlsx')
CATALOG_PATH = os.path.join(os.path.dirname(__file__), 'catalogo_formulario.json')
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
CATALOG_FILE_PATH = None
CATALOG = {}

def ensure_data_file():
    if not os.path.exists(DATA_PATH):
        # Try to restore from Excel if exists
        restored = False
        if os.path.exists(EXCEL_PATH):
            try:
                df = pd.read_excel(EXCEL_PATH)
                # Ensure headers match
                df = df.reindex(columns=DATA_HEADERS)
                df.to_csv(DATA_PATH, index=False)
                restored = True
            except Exception as e:
                print(f"Error restoring CSV from Excel: {e}")
        
        if not restored:
            with open(DATA_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(DATA_HEADERS)
    
    # Also ensure Excel exists if missing
    if not os.path.exists(EXCEL_PATH):
        update_excel_file()

def ensure_activities_file():
    if not os.path.exists(DATA_ACTIVITIES_PATH):
        # Try to restore from Excel if exists
        restored = False
        if os.path.exists(EXCEL_ACTIVITIES_PATH):
            try:
                df = pd.read_excel(EXCEL_ACTIVITIES_PATH)
                # Ensure headers match
                df = df.reindex(columns=DATA_ACTIVITIES_HEADERS)
                df.to_csv(DATA_ACTIVITIES_PATH, index=False)
                restored = True
            except Exception as e:
                print(f"Error restoring Activities CSV from Excel: {e}")
        
        if not restored:
            with open(DATA_ACTIVITIES_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(DATA_ACTIVITIES_HEADERS)
                
    # Also ensure Excel exists if missing
    if not os.path.exists(EXCEL_ACTIVITIES_PATH):
        update_activities_excel_file()

def sync_activities_db():
    """
    Synchronizes the internal CSV database with the Excel file.
    The Excel file is treated as the Source of Truth.
    If Excel exists, we update the CSV to match it.
    """
    if os.path.exists(EXCEL_ACTIVITIES_PATH):
        try:
            # Read Excel file
            df_excel = pd.read_excel(EXCEL_ACTIVITIES_PATH)
            
            # Ensure it has the correct headers (enforce schema)
            # This handles case where user might have deleted columns or reordered them
            for col in DATA_ACTIVITIES_HEADERS:
                if col not in df_excel.columns:
                    df_excel[col] = '' # Add missing columns
            
            df_excel = df_excel.reindex(columns=DATA_ACTIVITIES_HEADERS)
            
            # Write to CSV (Mirroring Excel to App Storage)
            df_excel.to_csv(DATA_ACTIVITIES_PATH, index=False)
        except Exception as e:
            print(f"Error syncing from Excel to CSV: {e}")
            # If sync fails (e.g. Excel open by user and locked), we fallback to existing CSV
            pass

def generate_excel_bytes():
    """Generates the Excel file in memory and returns a BytesIO object."""
    ensure_data_file()
    try:
        df = pd.read_csv(DATA_PATH)
    except Exception:
        df = pd.DataFrame(columns=DATA_HEADERS)
        
    if 'Fecha inicio' in df.columns:
        df['Fecha inicio'] = pd.to_datetime(df['Fecha inicio'], errors='coerce')
    
    # Ensure columns are in the correct order
    df = df.reindex(columns=DATA_HEADERS)
    
    sort_cols = [c for c in ['Fecha inicio','Municipio','Nombre paciente'] if c in df.columns]
    if sort_cols:
        df = df.sort_values(by=sort_cols, ascending=[True, True, True], na_position='last')
        
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Registros')
        ws = writer.book['Registros']
        ws.freeze_panes = 'A2'
        header_fill = PatternFill(fill_type='solid', start_color='EEF3FF', end_color='EEF3FF')
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val = '' if cell.value is None else str(cell.value)
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = min(48, max(12, max_len + 2))
    output.seek(0)
    return output

def update_excel_file():
    """Reads the current CSV and saves it as a formatted Excel file."""
    try:
        excel_bytes = generate_excel_bytes()
        with open(EXCEL_PATH, 'wb') as f:
            f.write(excel_bytes.getvalue())
    except Exception as e:
        print(f"Error updating Excel file (file might be open): {e}")

def generate_activities_excel_bytes():
    """Generates the Activities Excel file in memory."""
    ensure_activities_file()
    try:
        df = pd.read_csv(DATA_ACTIVITIES_PATH)
    except Exception as e:
        # Only ignore error if file is missing (should have been created by ensure) or empty
        # If file exists but is locked/unreadable, we should log it
        if os.path.exists(DATA_ACTIVITIES_PATH) and os.path.getsize(DATA_ACTIVITIES_PATH) > 0:
            print(f"Error reading activities CSV for Excel generation: {e}")
        df = pd.DataFrame(columns=DATA_ACTIVITIES_HEADERS)
        
    if 'Fecha' in df.columns:
        df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
        df = df.sort_values(by='Fecha', ascending=True)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Actividades')
        ws = writer.book['Actividades']
        ws.freeze_panes = 'A2'
        header_fill = PatternFill(fill_type='solid', start_color='EEF3FF', end_color='EEF3FF')
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val = '' if cell.value is None else str(cell.value)
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = min(60, max(12, max_len + 2))
    output.seek(0)
    return output

def update_activities_excel_file():
    try:
        excel_bytes = generate_activities_excel_bytes()
        with open(EXCEL_ACTIVITIES_PATH, 'wb') as f:
            f.write(excel_bytes.getvalue())
    except Exception as e:
        print(f"Error updating Activities Excel file: {e}")

def load_catalog():
    global CATALOG
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    if os.path.exists(CATALOG_PATH):
        try:
            with open(CATALOG_PATH, 'r', encoding='utf-8') as f:
                CATALOG = json.load(f)
        except Exception:
            CATALOG = {}
    else:
        CATALOG = {}
    cfg = CATALOG if isinstance(CATALOG, dict) else {}
    fp = cfg.get('catalog_file_path')
    if fp and os.path.exists(fp):
        global CATALOG_FILE_PATH
        CATALOG_FILE_PATH = fp

def save_catalog(cat):
    with open(CATALOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cat, f, ensure_ascii=False)

def validate_payload(p):
    req = ['fecha_inicio', 'municipio', 'nombre_prof', 'doc_prof', 'nombre_pac', 'doc_pac', 'procedimiento', 'panacea', 'novedad']
    if not all(p.get(k, '').strip() for k in req):
        return 'Complete todos los campos'
    try:
        datetime.strptime(p['fecha_inicio'], '%Y-%m-%d')
    except Exception:
        return 'Fecha en formato YYYY-MM-DD'
    pv = p.get('panacea', '').strip()
    if pv not in ('Sí', 'Si', 'No'):
        return 'Seleccione si se subió a Panacea'
    return None

PAGE_FORM = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Registro de Procedimientos</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #eaf2ff; color: #111; }
    .container { max-width: 95%; margin: 32px auto; padding: 0 16px; }
    .brand { text-align:center; margin-bottom: 18px; }
    .brand .box { display:inline-block; padding: 15px 30px; border-radius: 12px; background: linear-gradient(135deg, #1f3b8f, #2e5cff); color:#fff; font-weight: 600; letter-spacing: .5px; font-size: 24px; box-shadow: 0 4px 15px rgba(46, 92, 255, 0.3); }
    .card { background: #fff; border-radius: 12px; box-shadow: 0 8px 24px rgba(39,79,145,.08); padding: 20px; }
    .row { display: grid; grid-template-columns: 240px 1fr; gap: 10px; margin-bottom: 12px; align-items: center; }
    input, textarea, button, select { padding: 10px 12px; font-size: 14px; width: 100%; box-sizing: border-box; border: 1px solid #d5d9e2; border-radius: 8px; }
    input:focus, textarea:focus, select:focus { outline: 2px solid #2e5cff22; border-color: #2e5cff; }
    textarea { height: 110px; }
    .actions { margin-top: 16px; display: flex; gap: 12px; }
    .status { margin-top: 12px; }
    .notice { padding: 10px 12px; border-radius: 8px; background: {% if ok %}#E8F6EE{% else %}#FCE4E4{% endif %}; color: {% if ok %}#0B7A33{% else %}#8B0000{% endif %}; border: 1px solid {% if ok %}#A6E6BE{% else %}#F5B7B7{% endif %}; }
    .topbar { display:flex; justify-content: space-between; align-items:center; margin-bottom:16px; }
    .title { color: #1f3b8f; margin: 0; }
    .admin { text-decoration:none; background:#1f3b8f; color:#fff; padding:10px 14px; border-radius:8px; }
    .btn-primary { background:#2e5cff; color:#fff; border: none; }
    .btn-secondary { background:#e9eef9; color:#1f3b8f; border: none; }
    @media (max-width: 600px) {
      .row { grid-template-columns: 1fr; }
    }
    .tabs { display:flex; gap:10px; margin-bottom:20px; }
    .nav-btn { text-decoration:none; background:#e9eef9; color:#1f3b8f; padding:10px 14px; border-radius:8px; font-weight:600; }
    .nav-btn.active { background:#009688; color:#fff; }
    .btn-search { background:#ff9800; color:#fff; border:none; font-weight:600; }
  </style>
</head>
<body>
  <div class="container">
    <div class="brand"><div class="box">IPS GOLEMAN</div></div>

    <div class="tabs">
        <a class="nav-btn active" href="{{ url_for('index') }}" style="background-color: #009688;">Procedimientos</a>
        <a class="nav-btn" href="{{ url_for('activities') }}">Actividades</a>
    </div>

    <div class="card">
      <div class="topbar">
        <h2 class="title">Registro de Procedimientos</h2>
        <a class="admin" href="{{ url_for('admin') }}">Administrador</a>
      </div>
      
      <div style="margin-bottom: 20px; padding: 15px; background: #eef3ff; border-radius: 8px; border: 1px solid #d5d9e2;">
        <label style="font-weight:bold; display:block; margin-bottom:5px;">Buscar Registro por ID (Solo editar Novedad/Panacea)</label>
        <form method="post" action="{{ url_for('search_public') }}" style="display:flex; gap:10px; margin:0;">
            <input type="number" name="search_id" placeholder="Ingrese ID..." style="flex:1;" required>
            <button type="submit" class="btn-secondary" style="width:auto;">Buscar</button>
        </form>
      </div>

      <form method="post" action="{{ url_for('save') }}">
      <input type="hidden" name="id" value="{{ vals.get('id','') }}">
      <div class="row"><label>Nombre profesional</label>
        {% if edit_mode %}
          <input name="nombre_prof" value="{{ vals.get('nombre_prof','') }}" readonly style="background-color: #f9f9f9; color: #555;">
        {% else %}
            {% if catalog.get('nombre_prof') %}
              <select name="nombre_prof" id="nombre_prof" required>
                <option value="">Selecciona...</option>
                {% for v in catalog.get('nombre_prof') %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
              </select>
            {% else %}
              <input name="nombre_prof" id="nombre_prof" value="{{ vals.get('nombre_prof','') }}" required>
            {% endif %}
        {% endif %}
      </div>
      <div class="row"><label>Documento profesional</label>
        {% if edit_mode %}
          <input name="doc_prof" value="{{ vals.get('doc_prof','') }}" readonly style="background-color: #f9f9f9; color: #555;">
        {% else %}
            {% if catalog.get('prof_map') %}
              <input name="doc_prof" id="doc_prof" value="{{ vals.get('doc_prof','') }}" required readonly>
            {% elif catalog.get('doc_prof') %}
              <select name="doc_prof" required>
                <option value="">Selecciona...</option>
                {% for v in catalog.get('doc_prof') %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
              </select>
            {% else %}
              <input name="doc_prof" value="{{ vals.get('doc_prof','') }}" required>
            {% endif %}
        {% endif %}
      </div>
      <div class="row"><label>Nombre paciente</label>
        {% if edit_mode %}
          <input name="nombre_pac" value="{{ vals.get('nombre_pac','') }}" readonly style="background-color: #f9f9f9; color: #555;">
        {% else %}
          <input name="nombre_pac" value="{{ vals.get('nombre_pac','') }}" required>
        {% endif %}
      </div>
      <div class="row"><label>Documento paciente</label>
        {% if edit_mode %}
          <input name="doc_pac" value="{{ vals.get('doc_pac','') }}" readonly style="background-color: #f9f9f9; color: #555;">
        {% else %}
          <input name="doc_pac" value="{{ vals.get('doc_pac','') }}" required>
        {% endif %}
      </div>
      <div class="row"><label>Fecha inicio</label>
        {% if edit_mode %}
          <input type="text" name="fecha_inicio" value="{{ vals.get('fecha_inicio','') }}" readonly style="background-color: #f9f9f9; color: #555;">
        {% else %}
          <input type="date" name="fecha_inicio" value="{{ vals.get('fecha_inicio','') }}" required>
        {% endif %}
      </div>
      <div class="row"><label>Municipio</label>
        {% if edit_mode %}
          <input name="municipio" value="{{ vals.get('municipio','') }}" readonly style="background-color: #f9f9f9; color: #555;">
        {% else %}
            {% if catalog.get('municipio') %}
              <select name="municipio" required>
                <option value="">Selecciona...</option>
                {% for v in catalog.get('municipio') %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
              </select>
            {% else %}
              <input name="municipio" value="{{ vals.get('municipio','') }}" required>
            {% endif %}
        {% endif %}
      </div>
      <div class="row"><label>Procedimiento</label>
        {% if edit_mode %}
          <input name="procedimiento" value="{{ vals.get('procedimiento','') }}" readonly style="background-color: #f9f9f9; color: #555;">
        {% else %}
            {% if catalog.get('procedimiento') %}
              <select name="procedimiento" required>
                <option value="">Selecciona...</option>
                {% for v in catalog.get('procedimiento') %}<option value="{{ v }}">{{ v }}</option>{% endfor %}
              </select>
            {% else %}
              <input name="procedimiento" value="{{ vals.get('procedimiento','') }}" required>
            {% endif %}
        {% endif %}
      </div>
      <div class="row"><label>¿Se subió a Panacea?</label>
        <select name="panacea" required>
          <option value="">Selecciona...</option>
          <option value="Sí" {% if vals.get('panacea') in ['Sí','Si'] %}selected{% endif %}>Sí</option>
          <option value="No" {% if vals.get('panacea') == 'No' %}selected{% endif %}>No</option>
        </select>
      </div>
      <div class="row"><label>Novedad</label><textarea name="novedad" required>{{ vals.get('novedad','') }}</textarea></div>
      <div class="actions">
        <button class="btn-primary" type="submit">Guardar</button>
        {% if edit_mode %}
           <a href="{{ url_for('index') }}"><button class="btn-secondary" type="button">Cancelar Edición</button></a>
        {% else %}
           <button class="btn-secondary" type="reset">Limpiar</button>
        {% endif %}
      </div>
    </form>
    {% if status %}
      <div class="status"><div class="notice">{% if ok %}✔ {{ status }}{% else %}{{ status }}{% endif %}</div></div>
    {% endif %}
    </div>
  </div>
  <script>
    var profMap = JSON.parse('{{ prof_map_json|safe }}' || '{}');
    var nombreSel = document.getElementById('nombre_prof');
    var docInput = document.getElementById('doc_prof');
    function syncDoc() {
      if (!nombreSel || !docInput || !profMap) return;
      var n = nombreSel.value || '';
      docInput.value = profMap[n] || '';
    }
    if (nombreSel && docInput) {
      nombreSel.addEventListener('change', syncDoc);
      syncDoc();
    }
  </script>
</body>
</html>
"""

PAGE_ACTIVITIES = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Registro de Actividades</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #eaf2ff; color: #111; }
    .container { max-width: 95%; margin: 32px auto; padding: 0 16px; }
    .brand { text-align:center; margin-bottom: 18px; }
    .brand .box { display:inline-block; padding: 15px 30px; border-radius: 12px; background: linear-gradient(135deg, #1f3b8f, #2e5cff); color:#fff; font-weight: 600; letter-spacing: .5px; font-size: 24px; box-shadow: 0 4px 15px rgba(46, 92, 255, 0.3); }
    .card { background: #fff; border-radius: 12px; box-shadow: 0 8px 24px rgba(39,79,145,.08); padding: 20px; }
    .row { display: grid; grid-template-columns: 240px 1fr; gap: 10px; margin-bottom: 12px; align-items: center; }
    input, textarea, button, select { padding: 10px 12px; font-size: 14px; width: 100%; box-sizing: border-box; border: 1px solid #d5d9e2; border-radius: 8px; }
    input:focus, textarea:focus, select:focus { outline: 2px solid #2e5cff22; border-color: #2e5cff; }
    textarea { height: 110px; }
    .actions { margin-top: 16px; display: flex; gap: 12px; }
    .status { margin-top: 12px; }
    .notice { padding: 10px 12px; border-radius: 8px; background: {% if ok %}#E8F6EE{% else %}#FCE4E4{% endif %}; color: {% if ok %}#0B7A33{% else %}#8B0000{% endif %}; border: 1px solid {% if ok %}#A6E6BE{% else %}#F5B7B7{% endif %}; }
    .topbar { display:flex; justify-content: space-between; align-items:center; margin-bottom:16px; }
    .title { color: #1f3b8f; margin: 0; }
    .nav-btn { text-decoration:none; background:#e9eef9; color:#1f3b8f; padding:10px 14px; border-radius:8px; font-weight:600; }
    .nav-btn.active { background:#009688; color:#fff; }
    .btn-search { background:#ff9800; color:#fff; border:none; font-weight:600; }
    .admin { text-decoration:none; background:#1f3b8f; color:#fff; padding:10px 14px; border-radius:8px; }
    .btn-primary { background:#2e5cff; color:#fff; border: none; }
    .btn-secondary { background:#e9eef9; color:#1f3b8f; border: none; }
    @media (max-width: 600px) {
      .row { grid-template-columns: 1fr; }
    }
    .tabs { display:flex; gap:10px; margin-bottom:20px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="brand"><div class="box">IPS GOLEMAN</div></div>
    
    <div class="tabs">
        <a class="nav-btn" href="{{ url_for('index') }}">Procedimientos</a>
        <a class="nav-btn active" href="{{ url_for('activities') }}" style="background-color: #673ab7;">Actividades</a>
    </div>

    <div class="card">
      <div class="topbar">
        <h2 class="title">Registro de Actividades</h2>
        <div style="display:flex; gap:10px;">
            <a class="admin" href="{{ url_for('admin') }}">Administrador</a>
            <a class="admin" href="{{ url_for('activities') }}" title="Inicio Actividades">🏠</a>
        </div>
      </div>
      
      <!-- Bloque de Búsqueda para Edición -->
      <div style="margin-bottom: 20px; padding: 15px; background: #eef3ff; border-radius: 8px; border: 1px solid #d5d9e2;">
        <label style="font-weight:bold; display:block; margin-bottom:5px;">Consultar y Editar mis Actividades</label>
        <form method="get" action="{{ url_for('search_activities_public') }}" style="display:flex; gap:10px; margin:0; flex-wrap:wrap;">
            <div style="flex:1; min-width:200px;">
                {% if catalog.get('nombre_prof') %}
                  <select name="search_prof" required>
                    <option value="">Seleccione su nombre...</option>
                    {% for v in catalog.get('nombre_prof') %}
                        <option value="{{ v }}" {% if search_prof == v %}selected{% endif %}>{{ v }}</option>
                    {% endfor %}
                  </select>
                {% else %}
                  <input name="search_prof" placeholder="Nombre profesional..." value="{{ search_prof|default('') }}" required>
                {% endif %}
            </div>
            <button type="submit" class="btn-search" style="width:auto;">Buscar Actividades</button>
        </form>
      </div>

      {% if my_activities %}
      <div style="margin-bottom: 20px; overflow-x:auto;">
        <h3 style="font-size:16px; color:#1f3b8f; margin-bottom:10px;">Resultados para: {{ search_prof }}</h3>
        <table style="width:100%; border-collapse:collapse; font-size:14px;">
            <thead>
                <tr style="background:#f4f8ff; color:#1f3b8f;">
                    <th style="padding:8px; border-bottom:1px solid #eee;">Fecha</th>
                    <th style="padding:8px; border-bottom:1px solid #eee;">Actividad</th>
                    <th style="padding:8px; border-bottom:1px solid #eee;">Modificado</th>
                    <th style="padding:8px; border-bottom:1px solid #eee;">Acción</th>
                </tr>
            </thead>
            <tbody>
                {% for act in my_activities %}
                <tr>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{{ act.Fecha }}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee;">{{ act.Actividad }}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; font-size:12px; color:#666;">{{ act.Modificado if act.Modificado else '-' }}</td>
                    <td style="padding:8px; border-bottom:1px solid #eee; text-align:center;">
                        <form method="post" action="{{ url_for('edit_activity_prep') }}" style="margin:0;">
                            <input type="hidden" name="id" value="{{ act.ID }}">
                            <button class="btn-secondary" type="submit" style="padding:4px 10px; font-size:12px;">Editar</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
      </div>
      {% endif %}
      
      {% if not search_prof or vals.get('id') %}
      <form method="post" action="{{ url_for('save_activity') }}">
      <input type="hidden" name="id" value="{{ vals.get('id','') }}">
      <div class="row"><label>Fecha</label><input type="date" name="fecha" value="{{ vals.get('fecha','') }}" required></div>
      <div class="row"><label>Nombre profesional</label>
        {% if catalog.get('nombre_prof') %}
          <select name="nombre_prof" required>
            <option value="">Selecciona...</option>
            {% for v in catalog.get('nombre_prof') %}
                <option value="{{ v }}" {% if vals.get('nombre_prof') == v %}selected{% endif %}>{{ v }}</option>
            {% endfor %}
          </select>
        {% else %}
          <input name="nombre_prof" value="{{ vals.get('nombre_prof','') }}" required>
        {% endif %}
      </div>
      <div class="row"><label>Actividad / Observación</label><textarea name="actividad" required>{{ vals.get('actividad','') }}</textarea></div>
      <div class="actions">
        <button class="btn-primary" type="submit">Guardar Actividad</button>
        {% if vals.get('id') %}
            <a href="{{ url_for('activities') }}"><button class="btn-secondary" type="button">Cancelar Edición</button></a>
        {% else %}
            <button class="btn-secondary" type="reset">Limpiar</button>
        {% endif %}
      </div>
    </form>
    {% endif %}

    {% if status %}
      <div class="status"><div class="notice">{% if ok %}✔ {{ status }}{% else %}{{ status }}{% endif %}</div></div>
    {% endif %}
    </div>
  </div>
</body>
</html>
"""

PAGE_ADMIN = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Administrador</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #eaf2ff; color: #111; }
    .container { max-width: 1100px; margin: 32px auto; padding: 0 16px; }
    input, button, select { padding: 10px 12px; font-size: 14px; width: 100%; box-sizing: border-box; border: 1px solid #d5d9e2; border-radius: 8px; }
    .row { display: grid; grid-template-columns: 150px 1fr; gap: 10px; margin-bottom: 12px; align-items: center; }
    .status { margin-top: 12px; color: {{ 'green' if ok else '#b00020' }}; text-align: center; font-weight: 500; }
    .actions { display: flex; gap: 12px; margin-top: 16px; justify-content: center; }
    .actions button { width: auto; min-width: 120px; cursor: pointer; }
    a { text-decoration:none; }
    @media (max-width: 600px) {
      .row { grid-template-columns: 1fr; }
      .dashboard-grid { grid-template-columns: 1fr !important; }
    }
    .brand { text-align:center; margin-bottom: 24px; }
    .brand .box { display:inline-block; padding: 10px 18px; border-radius: 12px; background: #1f3b8f; color:#fff; font-weight: 600; letter-spacing: .5px; }
    .card { background: #fff; border-radius: 12px; box-shadow: 0 8px 24px rgba(39,79,145,.08); padding: 32px; }
    .login-card { max-width: 420px; margin: 0 auto; }
    .dashboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 20px; }
    .panel-section { background: #f8fbff; border: 1px solid #e1e9f5; border-radius: 10px; padding: 20px; }
    .panel-title { margin-top: 0; color: #1f3b8f; font-size: 18px; border-bottom: 2px solid #e1e9f5; padding-bottom: 10px; margin-bottom: 15px; }
    .btn-primary { background:#2e5cff; color:#fff; border: none; font-weight: 600; }
    .btn-secondary { background:#e9eef9; color:#1f3b8f; border: none; font-weight: 600; }
    .btn-danger { background:#fff1f0; color:#cf1322; border: 1px solid #ffa39e; font-weight: 600; }
    
    /* Tabs */
    .admin-tabs { display: flex; gap: 10px; margin-bottom: 20px; justify-content: center; }
    .tab-btn { background: #e9eef9; color: #1f3b8f; padding: 10px 20px; border-radius: 8px; border: none; font-weight: 600; cursor: pointer; }
    .tab-btn.active { background: #1f3b8f; color: #fff; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    
    /* Table */
    table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    th, td { text-align: left; padding: 10px; border-bottom: 1px solid #eee; }
    th { background: #f4f8ff; color: #1f3b8f; font-weight: 600; }
    tr:hover { background: #f9fbff; }
  </style>
  <script>
    function openTab(name) {
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(name).classList.add('active');
        document.getElementById('btn-' + name).classList.add('active');
        localStorage.setItem('adminTab', name);
    }
    document.addEventListener('DOMContentLoaded', () => {
        const last = localStorage.getItem('adminTab') || 'procs';
        openTab(last);
    });
  </script>
</head>
<body>
  <div class="container">
    <div class="brand"><div class="box">IPS GOLEMAN</div></div>
    
    {% if not logged %}
      <div class="card login-card">
      <h2 style="text-align:center; color:#1f3b8f; margin-top:0;">Acceso Administrativo</h2>
      <form method="post">
        <div class="row"><label>Usuario</label><input name="user" required></div>
        <div class="row"><label>Contraseña</label><input type="password" name="password" required></div>
        <div class="actions">
          <button class="btn-primary" type="submit">Ingresar</button>
          <a href="{{ url_for('index') }}"><button class="btn-secondary" type="button">Volver</button></a>
          <button class="btn-secondary" type="reset">Limpiar</button>
        </div>
      </form>
      </div>
    {% else %}
      <div class="admin-tabs">
        <button id="btn-procs" class="tab-btn active" onclick="openTab('procs')">Gestión Procedimientos</button>
        <button id="btn-acts" class="tab-btn" onclick="openTab('acts')">Seguimiento Actividades</button>
      </div>

      <div class="card">
        <h2 style="margin-top:0; color:#1f3b8f; border-bottom:1px solid #eee; padding-bottom:10px;">Panel de Control</h2>
        
        <!-- Tab: Procedimientos -->
        <div id="procs" class="tab-content active">
            <div class="dashboard-grid">
                <!-- Left Panel -->
                <div class="panel-section">
                  <h3 class="panel-title">Estadísticas y Descargas</h3>
                  <div style="font-size:32px; font-weight:bold; color:#1f3b8f; margin-bottom:8px;">{{ record_count }}</div>
                  <div style="color:#666; margin-bottom:20px;">Registros totales</div>
                  
                  <div style="display:flex; flex-direction:column; gap:10px;">
                    <a href="{{ url_for('download_excel') }}"><button class="btn-primary" type="button">Descargar Excel Completo</button></a>
                    <a href="{{ url_for('logout') }}"><button class="btn-danger" type="button">Cerrar Sesión</button></a>
                  </div>
                </div>
                
                <!-- Right Panel: Catalog Upload -->
                <div class="panel-section">
                  <h3 class="panel-title">Actualizar Catálogo</h3>
                  <form method="post" action="{{ url_for('upload_catalog') }}" enctype="multipart/form-data">
                    <div style="margin-bottom:12px;">
                      <label style="display:block; margin-bottom:8px; font-size:14px; color:#555;">Archivo Excel (.xlsx)</label>
                      <input type="file" name="file" accept=".xlsx,.xls" required>
                    </div>
                    <button class="btn-secondary" type="submit">Subir y Actualizar</button>
                  </form>
                  {% if catalog %}
                    <div style="margin-top:12px; font-size:13px; color:#0B7A33;">✓ Catálogo activo</div>
                  {% endif %}
                  {% if catalog_filename %}
                    <div style="margin-top:4px; font-size:12px; color:#666; word-break:break-all;">{{ catalog_filename }}</div>
                  {% endif %}
                </div>
            </div>
            
            <div class="panel-section" style="margin-top: 24px;">
                <h3 class="panel-title">Buscar y Editar Registro</h3>
                <form method="post" action="{{ url_for('search_edit') }}">
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <label style="min-width: 60px;">ID:</label>
                        <input name="search_id" type="number" placeholder="Ingrese ID" required style="width: 150px;">
                        <button class="btn-primary" type="submit" style="width: auto;">Buscar</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Tab: Actividades -->
        <div id="acts" class="tab-content">
            <div class="panel-section">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; border-bottom:2px solid #e1e9f5; padding-bottom:10px;">
                    <h3 class="panel-title" style="border:none; margin:0; padding:0;">Control de Actividades</h3>
                    <div style="font-weight:bold; color:#1f3b8f; font-size:16px;">
                        Total Registros: {{ activities_count }}
                        {% if filtered_activities_count is defined and filtered_activities_count != activities_count %}
                        <span style="font-size:14px; color:#666; font-weight:normal;">(Mostrando: {{ filtered_activities_count }})</span>
                        {% endif %}
                    </div>
                </div>

                <div style="display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap;">
                    <form method="get" action="{{ url_for('admin') }}" style="display:flex; gap:10px; align-items:flex-end; flex:1;">
                        <input type="hidden" name="tab" value="acts">
                        <div style="flex:1;">
                            <label style="display:block; margin-bottom:5px;">Filtrar por Profesional</label>
                            <select name="filter_prof" onchange="this.form.submit()">
                                <option value="">Todos los profesionales</option>
                                {% for p in profs %}
                                    <option value="{{ p }}" {% if filter_prof == p %}selected{% endif %}>{{ p }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div style="flex:1;">
                            <label style="display:block; margin-bottom:5px;">Filtrar por Fecha</label>
                            <input type="date" name="filter_date" value="{{ filter_date }}" onchange="this.form.submit()">
                        </div>
                        <button class="btn-secondary" type="submit" style="width:auto;">Filtrar</button>
                    </form>
                    <a href="{{ url_for('download_activities') }}" style="text-decoration:none;">
                        <button class="btn-primary" type="button" style="width:auto;">Descargar Todo (.xlsx)</button>
                    </a>
                </div>
            </div>
            
            <div style="margin-top:20px; overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th style="width:50px;">ID</th>
                            <th style="width:100px;">Fecha</th>
                            <th>Nombre Profesional</th>
                            <th>Actividad / Observación</th>
                            <th style="width:80px;">Acción</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for act in activities %}
                        <tr>
                            <td>{{ act.ID }}</td>
                            <td>{{ act.Fecha }}</td>
                            <td>{{ act['Nombre profesional'] }}</td>
                            <td>{{ act.Actividad }}</td>
                            <td style="text-align:center;">
                                <form method="post" action="{{ url_for('delete_activity', id=act.ID) }}" onsubmit="return confirm('¿Está seguro de eliminar esta actividad?');" style="margin:0;">
                                    <button class="btn-danger" type="submit" style="padding:4px 8px; font-size:12px;">Eliminar</button>
                                </form>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4" style="text-align:center; padding:20px; color:#666;">No hay actividades registradas.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

      </div>
    {% endif %}
    
    {% if status %}
      <div class="status">{{ status }}</div>
    {% endif %}
    
  </div>
</body>
</html>
"""

@app.route('/')
def index():
    load_catalog()
    return render_template_string(PAGE_FORM, status=None, ok=True, vals={'fecha_inicio': datetime.now().strftime('%Y-%m-%d')}, catalog=CATALOG, prof_map_json=json.dumps(CATALOG.get('prof_map', {}), ensure_ascii=False))

@app.route('/actividades')
def activities():
    load_catalog()
    return render_template_string(PAGE_ACTIVITIES, status=None, ok=True, vals={'fecha': datetime.now().strftime('%Y-%m-%d')}, catalog=CATALOG)

@app.route('/save_activity', methods=['POST'])
def save_activity():
    payload = {
        'id': request.form.get('id', '').strip(),
        'fecha': request.form.get('fecha', '').strip(),
        'nombre_prof': request.form.get('nombre_prof', '').strip(),
        'actividad': request.form.get('actividad', '').strip()
    }
    
    # Exclude ID from check
    if not all([payload['fecha'], payload['nombre_prof'], payload['actividad']]):
        load_catalog()
        return render_template_string(PAGE_ACTIVITIES, status='Complete todos los campos', ok=False, vals=payload, catalog=CATALOG)
        
    ensure_activities_file()
    sync_activities_db()
    
    try:
        df = pd.read_csv(DATA_ACTIVITIES_PATH)
    except Exception:
        df = pd.DataFrame(columns=DATA_ACTIVITIES_HEADERS)
        
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # If ID exists, we are editing
    status_msg = ""
    if payload['id']:
        try:
            edit_id = int(payload['id'])
            if 'ID' in df.columns and edit_id in df['ID'].values:
                # Update existing row
                idx = df.index[df['ID'] == edit_id].tolist()[0]
                df.at[idx, 'Fecha'] = payload['fecha']
                df.at[idx, 'Nombre profesional'] = payload['nombre_prof']
                df.at[idx, 'Actividad'] = payload['actividad']
                if 'Modificado' in df.columns:
                    df.at[idx, 'Modificado'] = now_str
                status_msg = "Actividad actualizada correctamente"
            else:
                # Fallback if ID not found
                return render_template_string(PAGE_ACTIVITIES, status='Error: ID de actividad no encontrado', ok=False, vals=payload, catalog=CATALOG)
        except ValueError:
            return render_template_string(PAGE_ACTIVITIES, status='Error: ID inválido', ok=False, vals=payload, catalog=CATALOG)
    else:
        # Create new
        new_id = df['ID'].max() + 1 if not df.empty and 'ID' in df.columns and not df['ID'].isnull().all() else 1
        if pd.isna(new_id): new_id = 1
        
        new_row = {
            'ID': int(new_id),
            'Fecha': payload['fecha'],
            'Nombre profesional': payload['nombre_prof'],
            'Actividad': payload['actividad'],
            'Creado': now_str,
            'Modificado': ''
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        status_msg = "Actividad guardada correctamente"
    
    df.to_csv(DATA_ACTIVITIES_PATH, index=False)
    update_activities_excel_file()
    
    load_catalog()
    # Reset form after save but keep user in loop if they want
    return render_template_string(PAGE_ACTIVITIES, status=status_msg, ok=True, vals={'fecha': datetime.now().strftime('%Y-%m-%d')}, catalog=CATALOG)

@app.route('/search_activities_public', methods=['GET'])
def search_activities_public():
    load_catalog()
    search_prof = request.args.get('search_prof', '').strip()
    my_activities = []
    
    if search_prof:
        ensure_activities_file()
        sync_activities_db()
        try:
            df = pd.read_csv(DATA_ACTIVITIES_PATH)
            if 'Nombre profesional' in df.columns:
                df_filtered = df[df['Nombre profesional'] == search_prof]
                if not df_filtered.empty:
                    if 'Fecha' in df.columns:
                        df_filtered = df_filtered.sort_values(by='Fecha', ascending=False)
                    my_activities = df_filtered.to_dict('records')
        except Exception as e:
            print(f"Error searching activities: {e}")
            
    return render_template_string(PAGE_ACTIVITIES, status=None, ok=True, vals={'fecha': datetime.now().strftime('%Y-%m-%d')}, catalog=CATALOG, search_prof=search_prof, my_activities=my_activities)

@app.route('/edit_activity_prep', methods=['POST'])
def edit_activity_prep():
    load_catalog()
    act_id = request.form.get('id')
    vals = {'fecha': datetime.now().strftime('%Y-%m-%d')}
    
    if act_id:
        ensure_activities_file()
        sync_activities_db()
        try:
            df = pd.read_csv(DATA_ACTIVITIES_PATH)
            df_item = df[df['ID'] == int(act_id)]
            if not df_item.empty:
                item = df_item.iloc[0]
                vals = {
                    'id': item['ID'],
                    'fecha': item['Fecha'],
                    'nombre_prof': item['Nombre profesional'],
                    'actividad': item['Actividad']
                }
        except Exception as e:
            print(f"Error prepping edit: {e}")

    return render_template_string(PAGE_ACTIVITIES, status="Modificando actividad ID: " + str(act_id), ok=True, vals=vals, catalog=CATALOG)

@app.route('/delete_activity/<int:id>', methods=['POST'])
def delete_activity(id):
    if not session.get('admin'):
        return redirect(url_for('admin'))
        
    ensure_activities_file()
    sync_activities_db()
    
    try:
        df = pd.read_csv(DATA_ACTIVITIES_PATH)
        if 'ID' in df.columns:
            # Filter out the row with the given ID
            df = df[df['ID'] != id]
            df.to_csv(DATA_ACTIVITIES_PATH, index=False)
            
            # Update Excel immediately to keep sync
            update_activities_excel_file()
    except Exception as e:
        print(f"Error deleting activity: {e}")
        
    return redirect(url_for('admin', tab='acts'))

@app.route('/save', methods=['POST'])
def save():
    payload = {k: request.form.get(k, '').strip() for k in ['id', 'nombre_prof','doc_prof','nombre_pac','doc_pac','fecha_inicio','municipio','procedimiento','panacea','novedad']}
    err = validate_payload(payload)
    if err:
        load_catalog()
        return render_template_string(PAGE_FORM, status=err, ok=False, vals=payload, catalog=CATALOG, prof_map_json=json.dumps(CATALOG.get('prof_map', {}), ensure_ascii=False))
    ensure_data_file()
    
    rec_id = payload.get('id')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    final_id = None
    
    try:
        df = pd.read_csv(DATA_PATH)
    except Exception:
        df = pd.DataFrame(columns=DATA_HEADERS)

    # Ensure ID column is numeric
    if 'ID' in df.columns:
        df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype(int)

    if rec_id and rec_id.isdigit():
        # Update existing
        rec_id = int(rec_id)
        idx = df.index[df['ID'] == rec_id].tolist()
        if idx:
            i = idx[0]
            df.at[i, 'Nombre profesional'] = payload['nombre_prof']
            df.at[i, 'Documento profesional'] = payload['doc_prof']
            df.at[i, 'Nombre paciente'] = payload['nombre_pac']
            df.at[i, 'Documento paciente'] = payload['doc_pac']
            df.at[i, 'Fecha inicio'] = payload['fecha_inicio']
            df.at[i, 'Municipio'] = payload['municipio']
            df.at[i, 'Procedimiento'] = payload['procedimiento']
            df.at[i, 'Subido a Panacea'] = 'Sí' if payload['panacea'] in ('Sí','Si') else 'No'
            df.at[i, 'Novedad'] = payload['novedad']
            df.at[i, 'Modificado'] = now_str
            final_id = rec_id
            msg = f'Actualizado correctamente. ID: {final_id}'
        else:
            # ID provided but not found? Treat as new or error. Let's treat as new for safety or error?
            # User expects to edit. If not found, maybe deleted.
            # Let's fallback to create new to preserve data
            rec_id = None
    
    if not final_id:
        # Create new
        new_id = df['ID'].max() + 1 if not df.empty and 'ID' in df.columns and not df['ID'].isnull().all() else 1
        if pd.isna(new_id): new_id = 1
        new_row = {
            'ID': int(new_id),
            'Nombre profesional': payload['nombre_prof'],
            'Documento profesional': payload['doc_prof'],
            'Nombre paciente': payload['nombre_pac'],
            'Documento paciente': payload['doc_pac'],
            'Fecha inicio': payload['fecha_inicio'],
            'Municipio': payload['municipio'],
            'Procedimiento': payload['procedimiento'],
            'Subido a Panacea': 'Sí' if payload['panacea'] in ('Sí','Si') else 'No',
            'Novedad': payload['novedad'],
            'Creado': now_str,
            'Modificado': ''
        }
        # Append using loc or concat
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        final_id = int(new_id)
        msg = f'Guardado exitosamente. Su ID es: {final_id}'

    # Save CSV
    if 'Fecha inicio' in df.columns:
        df['Fecha inicio'] = pd.to_datetime(df['Fecha inicio'], errors='coerce')
    sort_cols = [c for c in ['Fecha inicio','Municipio','Nombre paciente'] if c in df.columns]
    if sort_cols:
        df = df.sort_values(by=sort_cols, ascending=[True, True, True], na_position='last')
    
    # Re-save with all headers
    df = df.reindex(columns=DATA_HEADERS)
    df.to_csv(DATA_PATH, index=False)

    update_excel_file()
    load_catalog()
    return render_template_string(PAGE_FORM, status=msg, ok=True, vals={}, catalog=CATALOG, prof_map_json=json.dumps(CATALOG.get('prof_map', {}), ensure_ascii=False))

@app.route('/search_public', methods=['POST'])
def search_public():
    search_id = request.form.get('search_id')
    if not search_id:
        return redirect(url_for('index'))
    
    ensure_data_file()
    try:
        df = pd.read_csv(DATA_PATH)
        if 'ID' in df.columns:
            df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype(int)
        
        record = df[df['ID'] == int(search_id)]
        if record.empty:
            load_catalog()
            return render_template_string(PAGE_FORM, status=f'ID {search_id} no encontrado', ok=False, vals={}, catalog=CATALOG, prof_map_json=json.dumps(CATALOG.get('prof_map', {}), ensure_ascii=False))
        
        row = record.iloc[0]
        vals = {
            'id': str(row['ID']),
            'nombre_prof': str(row['Nombre profesional']) if pd.notna(row['Nombre profesional']) else '',
            'doc_prof': str(row['Documento profesional']) if pd.notna(row['Documento profesional']) else '',
            'nombre_pac': str(row['Nombre paciente']) if pd.notna(row['Nombre paciente']) else '',
            'doc_pac': str(row['Documento paciente']) if pd.notna(row['Documento paciente']) else '',
            'fecha_inicio': str(row['Fecha inicio']).split(' ')[0] if pd.notna(row['Fecha inicio']) else '',
            'municipio': str(row['Municipio']) if pd.notna(row['Municipio']) else '',
            'procedimiento': str(row['Procedimiento']) if pd.notna(row['Procedimiento']) else '',
            'panacea': str(row['Subido a Panacea']) if pd.notna(row['Subido a Panacea']) else '',
            'novedad': str(row['Novedad']) if pd.notna(row['Novedad']) else ''
        }
        
        load_catalog()
        return render_template_string(PAGE_FORM, status=f'Editando registro ID: {search_id}', ok=True, vals=vals, edit_mode=True, catalog=CATALOG, prof_map_json=json.dumps(CATALOG.get('prof_map', {}), ensure_ascii=False))
        
    except Exception as e:
        print(e)
        return redirect(url_for('index'))

@app.route('/admin', methods=['GET','POST'])
def admin():
    if request.method == 'POST':
        u = request.form.get('user','')
        p = request.form.get('password','')
        if ADMIN_USER and ADMIN_PASS:
            valid = (u == ADMIN_USER and p == ADMIN_PASS)
        else:
            valid = (u == 'admin' and p == 'admin')
        if valid:
            session['admin'] = True
            return redirect(url_for('admin'))
        return render_template_string(PAGE_ADMIN, logged=False, status='Credenciales inválidas', ok=False, catalog={}, record_count=0, catalog_filename=None)
    
    logged = session.get('admin') is True
    load_catalog()
    
    count = 0
    if os.path.exists(DATA_PATH):
        try:
            with open(DATA_PATH, 'r', encoding='utf-8') as f:
                rows = sum(1 for line in f)
                count = max(0, rows - 1)
        except Exception:
            count = 0

    catalog_filename = None
    if CATALOG.get('catalog_file_path'):
        catalog_filename = os.path.basename(CATALOG.get('catalog_file_path'))
        
    # Activities Data
    activities = []
    profs = []
    activities_count = 0
    filtered_activities_count = 0
    filter_prof = request.args.get('filter_prof', '').strip()
    filter_date = request.args.get('filter_date', '').strip()
    
    ensure_activities_file()
    sync_activities_db()
    try:
        df_act = pd.read_csv(DATA_ACTIVITIES_PATH)
        if not df_act.empty:
            activities_count = len(df_act)
            # Get unique professionals for filter
            if 'Nombre profesional' in df_act.columns:
                profs = sorted(df_act['Nombre profesional'].dropna().unique().tolist())
            
            # Apply filters
            if filter_prof:
                df_act = df_act[df_act['Nombre profesional'] == filter_prof]
            
            if filter_date:
                if 'Fecha' in df_act.columns:
                    df_act = df_act[df_act['Fecha'] == filter_date]

            filtered_activities_count = len(df_act)
            
            # Sort by ID desc
            if 'ID' in df_act.columns:
                df_act = df_act.sort_values(by='ID', ascending=False)
                
            activities = df_act.to_dict('records')
    except Exception as e:
        print(f"Error loading activities: {e}")
        activities = []

    return render_template_string(PAGE_ADMIN, logged=logged, status=None, ok=True, catalog=CATALOG, record_count=count, catalog_filename=catalog_filename, activities=activities, profs=profs, filter_prof=filter_prof, filter_date=filter_date, activities_count=activities_count, filtered_activities_count=filtered_activities_count)

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('index'))

@app.route('/download')
def download_excel():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    
    try:
        # Generate fresh Excel in memory
        output = generate_excel_bytes()
        return send_file(
            output, 
            as_attachment=True, 
            download_name='registros_procedimientos.xlsx', 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return f"Error generando archivo: {e}", 500

@app.route('/download_activities')
def download_activities():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    
    try:
        sync_activities_db()
        # Generate fresh Activities Excel in memory
        output = generate_activities_excel_bytes()
        return send_file(
            output, 
            as_attachment=True, 
            download_name='registros_actividades.xlsx', 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return f"Error generando archivo: {e}", 500

def extract_catalog(df):
    cols = {c.lower().strip(): c for c in df.columns}
    def get_unique(colnames):
        for c in colnames:
            key = c.lower().strip()
            if key in cols:
                return sorted([str(x).strip() for x in df[cols[key]].dropna().unique() if str(x).strip() != ''])
        return []
    prof_name_col = None
    for c in ['Nombre profesional','Profesional','Nombre del profesional']:
        k = c.lower().strip()
        if k in cols:
            prof_name_col = cols[k]
            break
    prof_doc_col = None
    for c in ['Documento profesional','Doc profesional','Documento del profesional']:
        k = c.lower().strip()
        if k in cols:
            prof_doc_col = cols[k]
            break
    prof_map = {}
    if prof_name_col and prof_doc_col:
        try:
            for _, row in df[[prof_name_col, prof_doc_col]].dropna().iterrows():
                n = str(row[prof_name_col]).strip()
                d = str(row[prof_doc_col]).strip()
                if n and d:
                    prof_map[n] = d
        except Exception:
            prof_map = {}
    return {
        'nombre_prof': get_unique(['Nombre profesional','Profesional','Nombre del profesional']),
        'doc_prof': get_unique(['Documento profesional','Doc profesional','Documento del profesional']),
        'nombre_pac': get_unique(['Nombre paciente','Paciente','Nombre del paciente']),
        'doc_pac': get_unique(['Documento paciente','Doc paciente','Documento del paciente']),
        'municipio': get_unique(['Municipio','Ciudad','Localidad']),
        'procedimiento': get_unique(['Procedimiento','Nombre procedimiento','Servicio']),
        'prof_map': prof_map
    }

@app.route('/search_edit', methods=['POST'])
def search_edit():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    
    search_id = request.form.get('search_id')
    if not search_id:
        return redirect(url_for('admin'))
        
    ensure_data_file()
    try:
        df = pd.read_csv(DATA_PATH)
        # Ensure ID column is numeric
        if 'ID' in df.columns:
            df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype(int)
            
        record = df[df['ID'] == int(search_id)]
        if record.empty:
            # Not found
            # Need to pass status back to admin. 
            # For simplicity, render admin with error.
            # We need to reload catalog stuff for admin view
            load_catalog()
            count = 0
            if os.path.exists(DATA_PATH):
                 with open(DATA_PATH, 'r', encoding='utf-8') as f:
                    count = max(0, sum(1 for line in f) - 1)
            
            catalog_filename = None
            if CATALOG.get('catalog_file_path'):
                catalog_filename = os.path.basename(CATALOG.get('catalog_file_path'))

            return render_template_string(PAGE_ADMIN, logged=True, status=f'ID {search_id} no encontrado', ok=False, catalog=CATALOG, record_count=count, catalog_filename=catalog_filename)
        
        # Found, prepare vals
        row = record.iloc[0]
        vals = {
            'id': str(row['ID']),
            'nombre_prof': str(row['Nombre profesional']) if pd.notna(row['Nombre profesional']) else '',
            'doc_prof': str(row['Documento profesional']) if pd.notna(row['Documento profesional']) else '',
            'nombre_pac': str(row['Nombre paciente']) if pd.notna(row['Nombre paciente']) else '',
            'doc_pac': str(row['Documento paciente']) if pd.notna(row['Documento paciente']) else '',
            'fecha_inicio': str(row['Fecha inicio']).split(' ')[0] if pd.notna(row['Fecha inicio']) else '',
            'municipio': str(row['Municipio']) if pd.notna(row['Municipio']) else '',
            'procedimiento': str(row['Procedimiento']) if pd.notna(row['Procedimiento']) else '',
            'panacea': str(row['Subido a Panacea']) if pd.notna(row['Subido a Panacea']) else '',
            'novedad': str(row['Novedad']) if pd.notna(row['Novedad']) else ''
        }
        
        load_catalog()
        # Render PAGE_FORM with vals. We need to indicate it's edit mode visually? 
        # The ID hidden field handles logic. 
        # Maybe add a status message "Editando registro ID X"
        return render_template_string(PAGE_FORM, status=f'Editando registro ID: {search_id}', ok=True, vals=vals, catalog=CATALOG, prof_map_json=json.dumps(CATALOG.get('prof_map', {}), ensure_ascii=False))
        
    except Exception as e:
        # Error
        print(e)
        return redirect(url_for('admin'))

@app.route('/admin/upload', methods=['POST'])
def upload_catalog():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    file = request.files.get('file')
    if not file:
        return render_template_string(PAGE_ADMIN, logged=True, status='Seleccione un archivo', ok=False, catalog=CATALOG, record_count=0, catalog_filename=None)
    try:
        filename = file.filename or 'catalogo.xlsx'
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ('.xlsx', '.xls'):
            return render_template_string(PAGE_ADMIN, logged=True, status='Formato no soportado', ok=False, catalog=CATALOG, record_count=0, catalog_filename=None)
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        saved_path = os.path.join(UPLOADS_DIR, 'catalogo_formulario' + ext)
        file.save(saved_path)
        df = pd.read_excel(saved_path)
        cat = extract_catalog(df)
        cat['catalog_file_path'] = saved_path
        save_catalog(cat)
        load_catalog()
        
        count = 0
        if os.path.exists(DATA_PATH):
             with open(DATA_PATH, 'r', encoding='utf-8') as f:
                count = max(0, sum(1 for line in f) - 1)

        catalog_filename = os.path.basename(saved_path)
        return render_template_string(PAGE_ADMIN, logged=True, status='Catálogo cargado', ok=True, catalog=CATALOG, record_count=count, catalog_filename=catalog_filename)
    except Exception:
        return render_template_string(PAGE_ADMIN, logged=True, status='Error leyendo Excel', ok=False, catalog=CATALOG, record_count=0, catalog_filename=None)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5028)), debug=False)
