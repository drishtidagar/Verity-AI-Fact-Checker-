"""Regenerate sample_data/Verity_Evaluation_Trap_Sample_v2.pdf (needs: pip install -r requirements-dev.txt)."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

CLAIMS = [
    "The chemical formula of water is H2O.",
    "The United Nations officially came into existence on 24 October 1945.",
    "The Eiffel Tower is located in Berlin, Germany.",
    "The Great Wall of China is easily visible to the unaided human eye from the Moon.",
    "An adult human skeleton typically contains 206 bones.",
    "The Burj Khalifa is 1,250 metres tall.",
    "The Amazon rainforest covers about 12 million square kilometres.",
    "The world's population is approximately 7 billion people.",
    "India's population is about 1.2 billion people.",
    "The concentration of carbon dioxide in Earth's atmosphere is about 400 parts per million.",
    "Pluto is classified as the ninth planet of the solar system.",
    "The Pacific Ocean is the largest ocean on Earth.",
    "Acme Industries recorded an internal customer churn rate of 4.1% in its 2023 fiscal year.",
]

def build(path="sample_data/Verity_Evaluation_Trap_Sample_v2.pdf"):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4, title="Verity Evaluation Trap Sample v2")
    story = [
        Paragraph("Verity Evaluation Trap Sample v2", styles["Title"]),
        Paragraph("Mixed factual statements for a controlled product demonstration. "
                  "Some statements are intentionally incorrect or out of date.", styles["BodyText"]),
        Spacer(1, 14),
    ]
    for i, c in enumerate(CLAIMS, 1):
        story += [Paragraph(f"{i}. {c}", styles["BodyText"]), Spacer(1, 6)]
    doc.build(story)

if __name__ == "__main__":
    build()
