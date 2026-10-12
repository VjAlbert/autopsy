"""Eccezioni condivise dall'intero pacchetto."""


class DrDeconstructError(Exception):
    """Radice di tutte le eccezioni del progetto."""


class AmbiguousInputError(DrDeconstructError):
    """Il tipo di input non è dichiarato e l'euristica non è abbastanza sicura."""


class BackendError(DrDeconstructError):
    """Il motore LLM ha fallito (non installato, errore, output non valido)."""


class RefusalError(BackendError):
    """Il modello ha rifiutato la richiesta."""


class SafetyError(DrDeconstructError):
    """Un'operazione hardware è stata bloccata da un controllo di sicurezza."""


class FetchError(DrDeconstructError):
    """Una risorsa web non è raggiungibile o la raccolta deve fermarsi."""


class RobotsDisallowedError(FetchError):
    """robots.txt del sito vieta l'accesso alla risorsa richiesta."""
