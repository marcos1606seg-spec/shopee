import streamlit as st
st.set_page_config(page_title="Caçador de Margens Shopee", layout="wide", page_icon="🛍️")
import pandas as pd
import json
import sqlite3
import bcrypt
from google import genai
from google.genai import types

# -----------------------------------------------------------------------------
# 1. CONEXÃO COM A API DE IA (GEMINI)
# -----------------------------------------------------------------------------
import os
try:
    _chave = st.secrets.get("GEMINI_API_KEY", None) if hasattr(st, "secrets") else None
except Exception:
    _chave = None
_chave = _chave or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
try:
    client = genai.Client(api_key=_chave) if _chave else None
    api_disponivel = client is not None
except Exception:
    client = None
    api_disponivel = False


# -----------------------------------------------------------------------------
# 2. ESTRUTURAÇÃO DO BANCO DE DADOS PERMANENTE (SQLITE)
# -----------------------------------------------------------------------------
def conectar_banco():
    conn = sqlite3.connect('cacador_margens.db')
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            custo_embalagem REAL DEFAULT 2.00,
            frete_entrada REAL DEFAULT 1.00,
            frete_gratis INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos_fornecedor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            categoria TEXT NOT NULL,
            custo REAL NOT NULL,
            preco_shopee_mercado REAL NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)
    conn.commit()
    return conn

# Inicialização imediata das tabelas
conectar_banco().close()

# -----------------------------------------------------------------------------
# 3. CONTROLADORES E LOGICA DE NEGÓCIO
# -----------------------------------------------------------------------------
def criar_usuario(email, senha):
    email = email.strip().lower()
    conn = conectar_banco()
    cursor = conn.cursor()
    senha_hash = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        cursor.execute("INSERT INTO usuarios (email, senha_hash) VALUES (?, ?)", (email, senha_hash))
        conn.commit()
        cursor.execute("SELECT id FROM usuarios WHERE email = ?", (email,))
        user_id = cursor.fetchone()[0]
        
        # Carga padrão de dados de demonstração para novos usuários
        produtos_originais = [
            (user_id, "Garrafa Térmica Inox 500ml", "Cozinha e Utensílios", 18.00, 39.90),
            (user_id, "Fone de Ouvido Bluetooth Y50", "Eletrônicos", 22.50, 49.99),
            (user_id, "Organizador de Maquiagem Acrílico", "Beleza e Cosméticos", 14.00, 29.90),
            (user_id, "Cabo USB-C Turbo 2 Metros", "Celulares e Acessórios", 8.00, 14.90),
            (user_id, "Suporte de Celular Automotivo Magnético", "Automotivo", 9.50, 24.90)
        ]
        cursor.executemany("""
            INSERT INTO produtos_fornecedor (usuario_id, nome, categoria, custo, preco_shopee_mercado)
            VALUES (?, ?, ?, ?, ?)
        """, produtos_originais)
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def verificar_login(email, senha):
    email = (email or '').strip().lower()
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute("SELECT id, senha_hash FROM usuarios WHERE email = ?", (email,))
    resultado = cursor.fetchone()
    conn.close()
    if resultado and bcrypt.checkpw(senha.encode('utf-8'), resultado[1].encode('utf-8')):
        return resultado[0]
    return None

def salvar_configuracoes_usuario(user_id, custo_emb, frete_ent, frete_gratis):
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE usuarios SET custo_embalagem = ?, frete_entrada = ?, frete_gratis = ? WHERE id = ?
    """, (custo_emb, frete_ent, 1 if frete_gratis else 0, user_id))
    conn.commit()
    conn.close()

def carregar_configuracoes_usuario(user_id):
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute("SELECT custo_embalagem, frete_entrada, frete_gratis, email FROM usuarios WHERE id = ?", (user_id,))
    resultado = cursor.fetchone()
    conn.close()
    return resultado

def carregar_produtos_usuario(user_id):
    conn = conectar_banco()
    df = pd.read_sql_query("SELECT * FROM produtos_fornecedor WHERE usuario_id = ?", conn, params=(user_id,))
    conn.close()
    return df.to_dict(orient='records')

def inserir_produto_usuario(user_id, nome, categoria, custo, preco_shopee):
    conn = conectar_banco()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO produtos_fornecedor (usuario_id, nome, categoria, custo, preco_shopee_mercado)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, nome, categoria, custo, preco_shopee))
    conn.commit()
    conn.close()

def chamar_ia_gerar_anuncio(nome_produto, categoria, preco_venda):
    if not api_disponivel:
        return {
            "titulo_seo": f"{nome_produto} Pronta Entrega Envio Rápido Nfe",
            "descricao_estrategica": f"Compre agora seu {nome_produto}! Estoque disponível no Brasil com envio imediato em até 24h úteis. Produto de alta qualidade na categoria {categoria} por apenas R$ {preco_venda}."
        }
    prompt = f"Gere um anúncio de alta conversão para a Shopee do produto '{nome_produto}' da categoria '{categoria}' vendido por R$ {preco_venda}. Retorne estritamente em JSON válido com as chaves 'titulo_seo' e 'descricao_estrategica'."
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7)
        )
        texto = (response.text or '').strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
        return json.loads(texto)
    except Exception as e:
        return {"titulo_seo": "Erro na Geração", "descricao_estrategica": f"Falha na API: {str(e)}"}

# -----------------------------------------------------------------------------
# 4. CONTROLE DE INTERFACE GRAFICA (STREAMLIT)
# -----------------------------------------------------------------------------
if 'logado' not in st.session_state:
    st.session_state.logado = False
if 'usuario_id' not in st.session_state:
    st.session_state.usuario_id = None

# TELA 1: AUTENTICAÇÃO DE SEGURANÇA
if not st.session_state.logado:
    st.title("🛍️ Acesso ao Sistema - Inteligência Operacional Shopee")
    tab_log, tab_cad = st.tabs(["🔐 Entrar", "📝 Cadastrar"])
    
    with tab_log:
        with st.form("f_login"):
            em_log = st.text_input("E-mail:")
            se_log = st.text_input("Senha:", type="password")
            if st.form_submit_button("Entrar no Painel"):
                uid = verificar_login(em_log, se_log)
                if uid:
                    st.session_state.logado = True
                    st.session_state.usuario_id = uid
                    st.rerun()
                else:
                    st.error("Credenciais inválidas.")

    with tab_cad:
        with st.form("f_cad"):
            em_cad = st.text_input("Definir E-mail:")
            se_cad = st.text_input("Definir Senha (mínimo 6 caracteres):", type="password")
            if st.form_submit_button("Confirmar Cadastro Permanente"):
                if em_cad and len(se_cad) >= 6:
                    if criar_usuario(em_cad, se_cad):
                        st.success("Conta configurada! Faça o login na aba ao lado.")
                    else:
                        st.error("E-mail já registrado.")
                else:
                    st.error("Insira dados válidos.")

# TELA 2: DASHBOARD OPERACIONAL COMPLETO
else:
    uid = st.session_state.usuario_id
    dados_user = carregar_configuracoes_usuario(uid)
    if not dados_user:
        st.session_state.logado = False
        st.session_state.usuario_id = None
        st.rerun()
    c_emb, f_ent, f_gratis, email_user = dados_user
    
    # Barra lateral de controle
    st.sidebar.markdown(f"👤 Operador: **{email_user}**")
    if st.sidebar.button("🚪 Sair do App"):
        st.session_state.logado = False
        st.session_state.usuario_id = None
        st.rerun()
        
    st.sidebar.divider()
    st.sidebar.header("⚙️ Variáveis de Custo")
    custo_emb_atual = st.sidebar.number_input("Custo de Embalagem (R$)", value=float(c_emb), step=0.5)
    frete_ent_atual = st.sidebar.number_input("Frete de Entrada (R$)", value=float(f_ent), step=0.5)
    gratis_atual = st.sidebar.checkbox("Programa Frete Grátis (+6% Taxa)", value=bool(f_gratis))
    
    if (custo_emb_atual, frete_ent_atual, bool(gratis_atual)) != (float(c_emb), float(f_ent), bool(f_gratis)):
        salvar_configuracoes_usuario(uid, custo_emb_atual, frete_ent_atual, gratis_atual)
    
    taxa_shopee = 0.20 if gratis_atual else 0.14
    TAXA_FIXA = 4.00
    LUCRO_CORTE = 0.10
    
    st.sidebar.divider()
    st.sidebar.subheader("➕ Adicionar Produto")
    with st.sidebar.form("f_add", clear_on_submit=True):
        n_p = st.text_input("Nome:")
        c_p = str(st.selectbox("Categoria:", ["Eletrônicos", "Cozinha e Utensílios", "Beleza e Cosméticos", "Celulares e Acessórios", "Automotivo", "Outros"]))
        cust_p = st.number_input("Custo Fornecedor (R$):", min_value=0.0, step=1.0)
        merc_p = st.number_input("Preço Shopee (R$):", min_value=0.0, step=1.0)
        if st.form_submit_button("Cadastrar"):
            if n_p and cust_p > 0 and merc_p > 0:
                inserir_produto_usuario(uid, n_p, c_p, cust_p, merc_p)
                st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("📁 Importar Lote (CSV)")
    csv_file = st.sidebar.file_uploader("Arquivo CSV (delimitador ';'):", type=["csv"])
    if csv_file is not None and st.session_state.get("csv_importado") != csv_file.file_id:
        try:
            df = pd.read_csv(csv_file, sep=";", decimal=",")
            df.columns = [c.strip().lower() for c in df.columns]
            obrig = {"nome", "categoria", "custo", "preco_shopee_mercado"}
            if obrig.issubset(df.columns):
                for _, r in df.iterrows():
                    inserir_produto_usuario(uid, str(r["nome"]), str(r["categoria"]), float(r["custo"]), float(r["preco_shopee_mercado"]))
                st.session_state.csv_importado = csv_file.file_id
                st.rerun()
            else:
                st.sidebar.error(f"Colunas obrigatórias: {', '.join(sorted(obrig))}")
        except Exception as e:
            st.sidebar.error(f"Erro: {e}")

    # Processamento logístico matemático
    produtos = carregar_produtos_usuario(uid)
    linhas = []
    for p in produtos:
        preco = float(p["preco_shopee_mercado"])
        custo_total = float(p["custo"]) + custo_emb_atual + frete_ent_atual
        taxas = preco * taxa_shopee + TAXA_FIXA
        lucro = preco - custo_total - taxas
        margem = lucro / preco if preco > 0 else 0.0
        linhas.append({
            "Produto": p["nome"], "Categoria": p["categoria"],
            "Custo Total (R$)": round(custo_total, 2), "Preço Shopee (R$)": round(preco, 2),
            "Taxas Shopee (R$)": round(taxas, 2), "Lucro (R$)": round(lucro, 2),
            "Margem (%)": round(margem * 100, 1),
            "Status": "✅ Viável" if margem >= LUCRO_CORTE else "❌ Descartar",
        })

    st.title("📊 Caçador de Margens Shopee")
    if not linhas:
        st.info("Nenhum produto cadastrado. Use a barra lateral para adicionar.")
        st.stop()

    df_res = pd.DataFrame(linhas).sort_values("Margem (%)", ascending=False)
    viaveis = df_res[df_res["Status"].str.startswith("✅")]
    c1, c2, c3 = st.columns(3)
    c1.metric("Produtos analisados", len(df_res))
    c2.metric("Viáveis (margem ≥ 10%)", len(viaveis))
    c3.metric("Lucro médio viáveis", f"R$ {viaveis['Lucro (R$)'].mean():.2f}" if len(viaveis) else "R$ 0,00")
    st.dataframe(df_res, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🤖 Gerador de Anúncio com IA")
    if not api_disponivel:
        st.caption("Chave GEMINI_API_KEY não configurada — usando texto modelo.")
    if len(viaveis):
        escolha = st.selectbox("Produto viável:", viaveis["Produto"].tolist())
        if st.button("Gerar Anúncio"):
            linha = viaveis[viaveis["Produto"] == escolha].iloc[0]
            with st.spinner("Gerando..."):
                anuncio = chamar_ia_gerar_anuncio(escolha, linha["Categoria"], f"{linha['Preço Shopee (R$)']:.2f}")
            st.text_input("Título SEO", anuncio.get("titulo_seo", ""))
            st.text_area("Descrição", anuncio.get("descricao_estrategica", ""), height=180)
    else:
        st.warning("Nenhum produto atinge a margem mínima de 10%.")
