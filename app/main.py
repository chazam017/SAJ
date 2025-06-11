from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from docx import Document
from datetime import datetime
from PIL import Image
from pdf2image import convert_from_bytes
import pytesseract
import shutil
import os
import io
import re

# caminhos
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler\Library\bin"

# inicialização
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # altere para ["http://localhost:5500"] se quiser limitar
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SALVOS_DIR = "saida"
UPLOAD_DIR = "uploads"
os.makedirs(SALVOS_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# o que faz as TAGs nos templates .docx serem substituídas
def substituir_tags(doc, dados):
    for p in doc.paragraphs:
        for tag, valor in dados.items():
            if f"{{{{{tag}}}}}" in p.text:
                p.text = p.text.replace(f"{{{{{tag}}}}}", valor)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for tag, valor in dados.items():
                    if f"{{{{{tag}}}}}" in cell.text:
                        cell.text = cell.text.replace(f"{{{{{tag}}}}}", valor)

# rota principal p/ gerar petição
@app.post("/gerar-peticao")
async def gerar_peticao(
    nome: str = Form(...),
    nascimento: str = Form(...),
    cpf: str = Form(...),
    rg: str = Form(...),
    beneficio: str = Form(...),
    enderecamento: str = Form(...),
    documentos: list[UploadFile] = File([])
):
    try:
        template_path = (
            "templates/LOAS_IDOSO_TAGS.docx"
            if beneficio == "idoso"
            else "templates/LOAS_DEFICIENTE_TAGS.docx"
        )

        doc = Document(template_path)

        dados_para_substituir = {
            "NOME": nome,
            "NASCIMENTO": nascimento,
            "CPF": cpf,
            "RG": rg,
            "ENDERECAMENTO": enderecamento,
        }

        substituir_tags(doc, dados_para_substituir)

        nome_limpo = "_".join(nome.strip().split()).lower()
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"peticao_{nome_limpo}_{timestamp}.docx"
        output_path = os.path.join(SALVOS_DIR, filename)

        doc.save(output_path)

        return JSONResponse({
            "success": True,
            "filename": filename,
            "url": f"http://localhost:8000/download/{filename}"
        })

    except Exception as e:
        return JSONResponse({"error": f"Erro ao gerar petição: {str(e)}"}, status_code=500)

# download por nome
@app.get("/download/{filename}")
async def download_peticao(filename: str):
    file_path = os.path.join(SALVOS_DIR, filename)
    if not os.path.exists(file_path):
        return JSONResponse({"error": "Arquivo não encontrado."}, status_code=404)
    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# pré-visualização como texto plano
@app.get("/download/ultimo")
async def download_ultimo_texto():
    arquivos = sorted(
        [f for f in os.listdir(SALVOS_DIR) if f.endswith(".docx")],
        key=lambda x: os.path.getmtime(os.path.join(SALVOS_DIR, x)),
        reverse=True
    )
    if not arquivos:
        return JSONResponse({"error": "Nenhuma petição encontrada."}, status_code=404)

    caminho = os.path.join(SALVOS_DIR, arquivos[0])
    doc = Document(caminho)
    texto = "\n".join([p.text for p in doc.paragraphs])
    return PlainTextResponse(texto)

# download do último arquivo/petição
@app.get("/download/ultimo-arquivo")
async def download_ultimo_arquivo():
    arquivos = sorted(
        [f for f in os.listdir(SALVOS_DIR) if f.endswith(".docx")],
        key=lambda x: os.path.getmtime(os.path.join(SALVOS_DIR, x)),
        reverse=True
    )
    if not arquivos:
        return JSONResponse({"error": "Nenhum documento encontrado"}, status_code=404)

    caminho = os.path.join(SALVOS_DIR, arquivos[0])
    return FileResponse(
        caminho,
        filename=arquivos[0],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# upload de documentos
@app.post("/upload-documentos")
async def upload_documentos(documentos: list[UploadFile] = File(...)):
    try:
        arquivos_salvos = []

        for doc in documentos:
            nome = doc.filename
            caminho = os.path.join(UPLOAD_DIR, nome)

            with open(caminho, "wb") as f:
                shutil.copyfileobj(doc.file, f)

            arquivos_salvos.append(nome)

        return JSONResponse({
            "success": True,
            "message": "Arquivos enviados com sucesso.",
            "arquivos_salvos": arquivos_salvos
        })

    except Exception as e:
        return JSONResponse({"error": f"Erro ao salvar arquivos: {str(e)}"}, status_code=500)

# OCR para extrair RMI dos documentos
@app.get("/extrair-rmi")
async def extrair_rmi():
    arquivos = sorted(
        [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith((".pdf", ".png", ".jpg", ".jpeg"))],
        key=lambda x: os.path.getmtime(os.path.join(UPLOAD_DIR, x)),
        reverse=True
    )
    if not arquivos:
        return JSONResponse({"error": "Nenhum documento disponível."}, status_code=400)

    texto_total = ""
    for nome in arquivos:
        caminho = os.path.join(UPLOAD_DIR, nome)
        with open(caminho, "rb") as f:
            content = f.read()

        try:
            if nome.lower().endswith((".png", ".jpg", ".jpeg")):
                img = Image.open(io.BytesIO(content))
                texto_total += pytesseract.image_to_string(img)

            elif nome.lower().endswith(".pdf"):
                imagens = convert_from_bytes(content, poppler_path=POPPLER_PATH)
                for img in imagens:
                    texto_total += pytesseract.image_to_string(img)
        except Exception as e:
            print(f"Erro ao processar {nome}: {e}")
            continue

    match = re.search(r"RMI\s*[:\-]?\s*R?\$?\s*(\d+[.,]?\d{0,2})", texto_total)
    if match:
        rmi = match.group(1).replace(",", ".")
        return JSONResponse({"rmi": rmi})

    return JSONResponse({"rmi": None})