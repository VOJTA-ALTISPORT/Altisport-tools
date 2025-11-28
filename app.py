import streamlit as st
import pandas as pd
import xmltodict
import requests
import io
import zipfile

# --- Nastavení stránky ---
st.set_page_config(page_title="Altisport XML Master", layout="wide", page_icon="⛷️")
st.title("⛷️ Altisport XML Master 23")

# --- Inicializace Paměti ---
if 'df' not in st.session_state: st.session_state.df = None
if 'xml_source_name' not in st.session_state: st.session_state.xml_source_name = ""
if 'found_lists' not in st.session_state: st.session_state.found_lists = {}
if 'excel_buffer' not in st.session_state: st.session_state.excel_buffer = None
if 'history' not in st.session_state: st.session_state.history = []

# --- Funkce pro Historii ---

def save_state():
    if len(st.session_state.history) > 5:
        st.session_state.history.pop(0)
    if st.session_state.df is not None:
        st.session_state.history.append(st.session_state.df.copy())

def undo_last_step():
    if st.session_state.history:
        st.session_state.df = st.session_state.history.pop()
        st.session_state.excel_buffer = None

# --- Funkce jádra ---

def clean_duplicate_columns(df):
    return df.loc[:, ~df.columns.duplicated(keep='last')]

def safe_preview_dataframe(df, rows=None):
    try:
        df = clean_duplicate_columns(df)
        preview = df.copy()
        if rows: preview = preview.head(rows)
        for col in preview.columns:
            if preview[col].dtype == 'object':
                preview[col] = preview[col].apply(lambda x: str(x) if isinstance(x, (list, dict)) else x)
        return preview
    except: 
        return df.head(rows) if rows else df

def extract_urls_smart(raw_data):
    found_urls = []
    def crawl(item):
        if isinstance(item, dict):
            if '#text' in item and isinstance(item['#text'], str):
                if 'http' in item['#text']: found_urls.append(item['#text'])
            for v in item.values(): crawl(v)
        elif isinstance(item, list):
            for i in item: crawl(i)
        elif isinstance(item, str):
            if len(item) > 10 and ('http' in item or 'www' in item): found_urls.append(item)
    crawl(raw_data)
    return list(dict.fromkeys(found_urls))

def normalize_column_to_list_safe(df, col_name):
    """
    HYBRIDNÍ FIX: 
    Pokud buňka obsahuje data -> vrátí seznam [data].
    Pokud je prázdná (jednoduchý produkt) -> vrátí [{}] (seznam s prázdným slovníkem).
    Tím zajistíme, že 'explode' ten řádek nezabije, ale zachová ho.
    """
    def fix_item(x):
        if isinstance(x, list): return x
        if isinstance(x, dict): return [x]
        # Tady je změna: místo [] vracíme [{}]
        return [{}] 
    return df[col_name].apply(fix_item)

def reset_excel():
    st.session_state.excel_buffer = None

def find_all_lists_recursive(data, path="", results=None):
    if results is None: results = {}
    if isinstance(data, list):
        if len(data) > 0: results[f"{path} (Položek: {len(data)})"] = data
        return results
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path} > {key}" if path else key
            find_all_lists_recursive(value, new_path, results)
    return results

# --- UI LOGIKA ---

with st.sidebar:
    st.header("1. Vstup dat")
    source_type = st.radio("Zdroj:", ["Nahrát soubor", "URL"])
    
    raw_content = None
    file_name = None
    process_trigger = False

    if source_type == "Nahrát soubor":
        uploaded_file = st.file_uploader("Soubor", type=['xml', 'zip'])
        if uploaded_file and st.button("🚀 Analyzovat soubor"):
            raw_content = uploaded_file.read()
            file_name = uploaded_file.name
            process_trigger = True
    else: 
        url_input = st.text_input("URL:")
        if url_input and st.button("🚀 Analyzovat URL"):
            file_name = url_input
            process_trigger = True
    
    if process_trigger:
        with st.status("Pracuji na tom...", expanded=True) as status:
            if source_type == "URL":
                status.write("📡 Připojuji se k serveru...")
                try:
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    response = requests.get(url_input, headers=headers, timeout=180)
                    response.raise_for_status()
                    raw_content = response.content
                    status.write("✅ Staženo.")
                except Exception as e:
                    status.update(label="Chyba!", state="error")
                    st.error(f"Chyba: {e}")
                    st.stop()

            if raw_content.startswith(b'PK'):
                status.write("📦 Rozbaluji ZIP...")
                try:
                    with zipfile.ZipFile(io.BytesIO(raw_content)) as z:
                        xml_filename = next((n for n in z.namelist() if n.lower().endswith('.xml')), z.namelist()[0])
                        raw_content = z.read(xml_filename)
                except: pass

            status.write("🔤 Dekóduji text...")
            text_content = None
            for enc in ['utf-8', 'windows-1250', 'latin-1']:
                try:
                    text_content = raw_content.decode(enc).strip()
                    if text_content.startswith('\ufeff'): text_content = text_content[1:]
                    break
                except: continue
            
            if not text_content:
                status.update(label="Chyba kódování!", state="error")
                st.stop()

            status.write("🔍 Analyzuji XML...")
            try:
                doc = xmltodict.parse(text_content)
                lists = find_all_lists_recursive(doc)
                st.session_state.found_lists = lists
                st.session_state.xml_source_name = file_name
                st.session_state.df = None
                st.session_state.history = []
                reset_excel()
                status.update(label="Hotovo! ✅", state="complete", expanded=False)
                st.rerun()
            except Exception as e:
                status.update(label="Chyba XML!", state="error")
                st.error(f"Chyba: {e}")
                st.stop()

    if st.session_state.found_lists:
        st.divider()
        if st.button("❌ Reset"):
            st.session_state.found_lists = {}
            st.session_state.df = None
            st.session_state.history = []
            reset_excel()
            st.rerun()

# --- HLAVNÍ OKNO ---

if st.session_state.found_lists and st.session_state.df is None:
    st.subheader(f"2. Vyber data: {st.session_state.xml_source_name}")
    sorted_keys = sorted(st.session_state.found_lists.keys(), key=lambda x: int(x.split('Položek: ')[1].replace(')', '')), reverse=True)
    sel = st.selectbox("Hlavní struktura:", sorted_keys)

    if st.button("⬇️ Načíst do tabulky"):
        raw = st.session_state.found_lists[sel]
        st.session_state.df = clean_duplicate_columns(pd.json_normalize(raw))
        st.session_state.history = []
        reset_excel()
        st.rerun()

if st.session_state.df is not None:
    main_df = st.session_state.df
    
    # --- FILTRACE & HLEDÁNÍ ---
    with st.expander("🔍 FILTRACE A HLEDÁNÍ V DATECH", expanded=True):
        col_f1, col_f2 = st.columns([1, 3])
        with col_f1:
            filter_col = st.selectbox("Hledat ve sloupci:", ["Všechny sloupce"] + list(main_df.columns))
        with col_f2:
            search_query = st.text_input("Hledaný text (EAN, ID, Název...):", placeholder="Napiš co hledáš...")

    if search_query:
        if filter_col == "Všechny sloupce":
            mask = main_df.astype(str).apply(lambda x: x.str.contains(search_query, case=False, na=False)).any(axis=1)
            filtered_df = main_df[mask]
        else:
            mask = main_df[filter_col].astype(str).str.contains(search_query, case=False, na=False)
            filtered_df = main_df[mask]
    else:
        filtered_df = main_df

    # --- DASHBOARD ---
    col_stat1, col_stat2, col_stat3 = st.columns([2, 1, 1])
    
    with col_stat1:
        st.metric(label="Zobrazeno / Celkem", value=f"{len(filtered_df)} / {len(main_df)}")
    
    with col_stat2:
        if st.session_state.history:
            if st.button("↩️ Zpět o krok"):
                undo_last_step()
                st.rerun()
        else:
            st.button("↩️ Zpět o krok", disabled=True)
            
    with col_stat3:
         st.caption(f"Historie: {len(st.session_state.history)}/5")

    st.dataframe(safe_preview_dataframe(filtered_df, rows=None), use_container_width=True)

    # --- OPERACE (Matrix) ---
    cand = [c for c in main_df.columns if main_df[c].dtype == 'object' and 
            isinstance(main_df[c].dropna().iloc[0] if not main_df[c].dropna().empty else None, (list, dict))]
    
    st.divider()
    st.header("3. Úpravy (Matrix)")

    if cand:
        target = st.selectbox("Sloupec k úpravě:", cand)
        c1, c2 = st.columns(2)
        
        with c1:
            st.markdown("### ⬇️ Varianty (EAN)")
            if st.button("Rozbalit na ŘÁDKY"):
                with st.spinner("Rozbaluji..."):
                    save_state()
                    df_work = st.session_state.df
                    
                    # Tady voláme tu SAFE verzi
                    df_work[target] = normalize_column_to_list_safe(df_work, target)
                    ex = df_work.explode(target).reset_index(drop=True)
                    
                    safe_list = [x if isinstance(x, dict) else {} for x in ex[target]]
                    sub = pd.json_normalize(safe_list)
                    sub.columns = [f"{target}.{c}" for c in sub.columns]
                    
                    # Mazání duchů
                    cols_in_ex = set(ex.columns)
                    cols_in_sub = set(sub.columns)
                    overlap = cols_in_ex.intersection(cols_in_sub)
                    ex_clean = ex.drop(columns=list(overlap))
                    if target in ex_clean.columns: ex_clean = ex_clean.drop(columns=[target])
                        
                    new_df = pd.concat([ex_clean, sub], axis=1)
                    st.session_state.df = clean_duplicate_columns(new_df)
                    reset_excel() 
                    st.rerun()

        with c2:
            st.markdown("### ➡️ Fotky (Sloupce)")
            if st.button("Rozložit do SLOUPCŮ"):
                with st.spinner("Extrahuji..."):
                    save_state()
                    df_work = st.session_state.df
                    urls = df_work[target].apply(extract_urls_smart)
                    exp = urls.apply(pd.Series)
                    clean_name = target.replace('.', '_').replace('>', '_')
                    exp.columns = [f"{clean_name}_{i+1}" for i in exp.columns]
                    st.session_state.df = pd.concat([df_work.drop(columns=[target]), exp], axis=1)
                    st.session_state.df = clean_duplicate_columns(st.session_state.df)
                    reset_excel() 
                    st.rerun()
    else:
        st.success("✅ Vše rozbaleno.")

    st.divider()
    
    # --- EXPORT ---
    st.header("4. Export")
    
    all_cols = sorted(main_df.columns)
    keys = ['EAN', 'NAME', 'NAZEV', 'PRICE', 'CENA', 'STOCK', 'QTY', 'CODE', 'KOD', 'SIZE', 'VELIKOST', 'IMG', 'URL', 'MODEL', 'VAT', 'DPH']
    pre = [c for c in all_cols if any(k in c.upper() for k in keys)]
    
    sel_cols = st.multiselect("Vyber sloupce:", all_cols, default=pre)
    export_mode = st.radio("Co chceš exportovat?", ["Pouze filtrovaná data (to, co vidím)", "Všechna data"], horizontal=True)

    if sel_cols:
        preview_export = filtered_df[sel_cols] if export_mode.startswith("Pouze") else main_df[sel_cols]
        st.caption("Náhled exportu (Top 5):")
        st.dataframe(safe_preview_dataframe(preview_export, rows=5), use_container_width=True)

    col_btn1, col_btn2 = st.columns([1, 1])

    with col_btn1:
        if st.button("🔄 PŘEVÉST DO EXCELU", type="primary"):
            if sel_cols:
                with st.spinner("Generuji Excel..."):
                    try:
                        df_to_export = filtered_df if export_mode.startswith("Pouze") else main_df
                        output = io.BytesIO()
                        export_df = df_to_export[sel_cols].astype(str)
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            export_df.to_excel(writer, index=False)
                        st.session_state.excel_buffer = output.getvalue()
                        st.success(f"Hotovo! ({len(df_to_export)} řádků)")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Chyba: {e}")
            else:
                st.warning("Vyber sloupce!")

    with col_btn2:
        if st.session_state.excel_buffer is not None:
            st.download_button(
                label="📥 STÁHNOUT SOUBOR (.xlsx)",
                data=st.session_state.excel_buffer,
                file_name="altisport_export.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
