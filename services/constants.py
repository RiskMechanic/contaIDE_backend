# services/constants.py
# Scopo: mettere codici contabili fissi e mappature di default, così puoi referenziarli ovunque.

from dataclasses import dataclass

@dataclass(frozen=True)
class AccountCodes:
    # -------------------
    # Attività
    # -------------------
    CREDITI_CLIENTI = "1410"
    IVA_A_CREDITO = "1411"
    BANCA_CC = "1432"
    CASSA = "1431"

    # -------------------
    # Passività
    # -------------------
    DEBITI_FORNITORI = "2310"
    IVA_A_DEBITO = "2321"

    # -------------------
    # Ricavi
    # -------------------
    VENDITE_PRESTAZIONI = "4100"

    # -------------------
    # Costi
    # -------------------
    COSTI_SERVIZI = "3200"       # servizi generici
    ONERI_FINANZIARI = "3500"    # spese bancarie / interessi

