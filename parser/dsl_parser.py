from services.api import create_sales_invoice
from decimal import Decimal

# esempio di interpretazione
def parse_and_post(command: str, user_id: str):
    if command.startswith("FATTURA CLIENTE"):
        # parsing semplice
        parts = command.split()
        amount = Decimal(parts[-1])
        doc_no = parts[2]
        return create_sales_invoice(
            date="2025-12-14",
            customer="Mario Rossi",
            doc_no=doc_no,
            net_amount=amount,
            vat_rate=Decimal("0.22"),
            user_id=user_id
        )
