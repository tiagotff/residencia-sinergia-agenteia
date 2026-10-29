"""Documentos sintéticos para exercitar o Agente 1.

Todos os nomes, CRMs e textos são fictícios. Requer o extra ``dev`` (reportlab).
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

TEXTS = {
    "atestado_medico": [
        "ATESTADO MÉDICO",
        "Atesto, para os devidos fins, que o(a) paciente Colaborador Fictício 1001",
        "necessita de 3 (três) dias de afastamento de suas atividades",
        "a partir de 27/10/2026.",
        "Campinas, 27/10/2026",
        "Dra. Exemplo Fictícia — CRM 000000/SP",
    ],
    "declaracao_comparecimento": [
        "DECLARAÇÃO DE COMPARECIMENTO",
        "Declaro que Colaborador Fictício 1002 compareceu a consulta",
        "no dia 27/10/2026, das 14h às 16h.",
        "Dr. Exemplo Fictício — CRM 000001/SP",
    ],
    "atestado_acompanhante": [
        "ATESTADO DE ACOMPANHANTE",
        "Atesto que Colaborador Fictício 1003 esteve como acompanhante",
        "de familiar em atendimento no dia 27/10/2026.",
        "Dra. Exemplo Fictícia — CRM 000002/SP",
    ],
    "receita_medica": [
        "RECEITUÁRIO",
        "Paciente: Colaborador Fictício 1004",
        "Uso oral: medicamento fictício, 1 comprimido a cada 8 horas.",
        "Dr. Exemplo Fictício — CRM 000003/SP",
    ],
}


def pdf_bytes(lines: list[str]) -> bytes:
    """Gera um PDF de uma página com camada de texto."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 780
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 24
    pdf.save()
    return buffer.getvalue()


def image_of(lines: list[str], size: tuple[int, int] = (1240, 1754)) -> Image.Image:
    """Desenha o texto numa folha branca, como uma foto bem tirada."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(12, size[0] // 34))
    y = size[1] // 12
    for line in lines:
        draw.text((size[0] // 14, y), line, fill="black", font=font)
        y += int(font.size * 1.8)
    return image


def png_bytes(image: Image.Image) -> bytes:
    """Serializa a imagem em PNG."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def scanned_pdf_bytes(lines: list[str]) -> bytes:
    """Gera um PDF só com imagem (sem camada de texto), como um escaneamento."""
    buffer = io.BytesIO()
    image_of(lines).save(buffer, format="PDF")
    return buffer.getvalue()


def generate_samples(folder: Path) -> list[Path]:
    """Grava o conjunto completo de amostras e devolve os caminhos."""
    folder.mkdir(parents=True, exist_ok=True)
    medical = TEXTS["atestado_medico"]
    files = {f"{name}.pdf": pdf_bytes(lines) for name, lines in TEXTS.items()}
    files |= {
        "atestado_escaneado.pdf": scanned_pdf_bytes(medical),
        "atestado_foto.png": png_bytes(image_of(medical)),
        "atestado_foto_desfocada.png": png_bytes(
            image_of(medical).filter(ImageFilter.GaussianBlur(10))
        ),
        "atestado_foto_pequena.png": png_bytes(image_of(medical, (300, 420))),
        "imagem_em_branco.png": png_bytes(Image.new("RGB", (1240, 1754), "white")),
        "pdf_corrompido.pdf": b"%PDF-1.4\nconteudo quebrado",
        "anotacao.txt": "texto simples, formato não aceito".encode(),
    }
    for name, content in files.items():
        (folder / name).write_bytes(content)
    return [folder / name for name in files]
