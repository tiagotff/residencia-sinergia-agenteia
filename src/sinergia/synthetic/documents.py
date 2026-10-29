"""Documentos sintéticos para exercitar os Agentes 1, 2 e 4.

Todos os nomes, CRMs e textos são fictícios; os CRMs da faixa 900000 constam só no
registro fictício ``config/crm_registry.yaml``. Requer o extra ``dev`` (reportlab).
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIGNATURE = "Assinatura e carimbo do médico"
DOCTOR = "Dra. Helena Ficticia Ramos — CRM 900123/SP"


def certificate(
    days: int,
    start: str,
    issued: str | None = None,
    doctor: str = DOCTOR,
    cid: str | None = None,
    signed: bool = True,
) -> list[str]:
    """Linhas de um atestado médico fictício."""
    lines = [
        "ATESTADO MÉDICO",
        "Paciente: Joana Exemplo da Silva",
        f"Atesto que a paciente acima necessita de {days}",
        f"dias de afastamento a partir de {start}.",
    ]
    if cid:
        lines.append(f"CID: {cid} (informado com autorização da paciente)")
    lines += [f"Campinas, {issued or start}", doctor]
    return lines + ([SIGNATURE] if signed else [])


TEXTS = {
    "atestado_medico": certificate(3, "27/10/2026"),
    "declaracao_comparecimento": [
        "DECLARAÇÃO DE COMPARECIMENTO",
        "Paciente: Joana Exemplo da Silva",
        "Declaro que a paciente acima compareceu a consulta",
        "no dia 27/10/2026, das 14h às 16h.",
        "Dr. Marcos Ficticio Lima — CRM 900456/SP",
        SIGNATURE,
    ],
    "atestado_acompanhante": [
        "ATESTADO DE ACOMPANHANTE",
        "Paciente: Joana Exemplo da Silva",
        "Atesto que a paciente acima esteve como acompanhante",
        "de familiar em atendimento no dia 27/10/2026.",
        "Dra. Paula Ficticia Nunes — CRM 900789/SP",
        SIGNATURE,
    ],
    "receita_medica": [
        "RECEITUÁRIO",
        "Paciente: Joana Exemplo da Silva",
        "Uso oral: medicamento fictício, 1 comprimido a cada 8 horas.",
        "Dr. Marcos Ficticio Lima — CRM 900456/SP",
    ],
    "atestado_longo_cid": certificate(20, "27/10/2026", cid="J11"),
    "atestado_datas_incoerentes": certificate(3, "27/10/2026", issued="05/11/2026"),
    "atestado_crm_aposentado": certificate(
        3, "27/10/2026", doctor="Dr. Rafael Ficticio Costa — CRM 900321/SP"
    ),
    "atestado_sem_assinatura": certificate(
        3, "27/10/2026", doctor="Dra. Helena Ficticia Ramos", signed=False
    ),
    "atestado_cid_outubro": certificate(10, "01/10/2026", cid="J11"),
    "atestado_acentos": [
        "ATESTADO MÉDICO",
        "Paciente: Márcia Conceição Antônio",
        "Atesto que a paciente acima necessita de 2",
        "dias de afastamento a partir de 27/10/2026.",
        "São José dos Campos, 27/10/2026",
        "Dr. João Fictício Araújo — CRM 900456/SP",
        SIGNATURE,
    ],
    "atestado_cid_novembro": certificate(8, "27/10/2026", cid="J11.1"),
    "atestado_retorno_35dias": certificate(35, "27/10/2026"),
    "atestado_lesao_punho": certificate(5, "27/10/2026", cid="S62.5"),
}


VACATIONS_CSV = (
    "employee_id;start_date;end_date\n7007;26/10/2026;09/11/2026\n7008;01/12/2026;30/12/2026\n"
)
"""Férias fictícias no formato do Excel em português (ponto e vírgula)."""


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
    font = _font(max(12, size[0] // 40))
    y = size[1] // 12
    for line in lines:
        draw.text((size[0] // 16, y), line, fill="black", font=font)
        y += int(font.size * 1.8)
    return image


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Fonte com os acentos do português (Vera, que acompanha o reportlab).

    A fonte embutida do Pillow não desenha letras acentuadas: o "é" vira um quadrado,
    e a imagem deixaria de representar um atestado real.
    """
    import reportlab

    return ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"), size)


def png_bytes(image: Image.Image) -> bytes:
    """Serializa a imagem em PNG."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def phone_photo_bytes(lines: list[str]) -> bytes:
    """Simula uma foto de celular: fundo de mesa, leve inclinação, desfoque e JPEG."""
    page = image_of(lines)
    table = Image.new("RGB", (page.width + 80, page.height + 80), (205, 200, 190))
    table.paste(page, (40, 40))
    tilted = table.rotate(2.5, expand=True, fillcolor=(120, 115, 105))
    buffer = io.BytesIO()
    tilted.filter(ImageFilter.GaussianBlur(1.2)).save(buffer, format="JPEG", quality=55)
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
        "atestado_foto_acentos.png": png_bytes(image_of(TEXTS["atestado_acentos"])),
        "atestado_foto_celular.jpg": phone_photo_bytes(TEXTS["atestado_acentos"]),
        "ferias.csv": VACATIONS_CSV.encode("utf-8"),
    }
    for name, content in files.items():
        (folder / name).write_bytes(content)
    return [folder / name for name in files]
