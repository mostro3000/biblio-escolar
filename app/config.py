"""Configuración de la app, leída de variables de entorno / /opt/biblio/.env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="/opt/biblio/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "biblio"
    # Vacío hasta que se configure PostgreSQL. Ej:
    #   postgresql+psycopg://biblio:PASS@localhost:5432/biblio
    database_url: str = ""

    # Ventana del QR rotativo (TOTP) en segundos. El código del alumno cambia
    # cada `qr_step_seconds`; el servidor tolera ±1 ventana (desfase de reloj).
    # Recomendado 30–60. Cambiar acá (o por env QR_STEP_SECONDS) sin tocar código.
    qr_step_seconds: int = 30

    # Rate limiting por IP (backstop anti fuerza-bruta / enumeración). En memoria y
    # por worker (con 2 workers el límite efectivo es ~2x). Ajustables por env.
    # OJO: si se hace onboarding guiado de un curso entero detrás de un mismo WiFi
    # (NAT = una sola IP), subir `onboarding_rate_max`.
    login_rate_max: int = 10          # intentos de login por ventana
    login_rate_window: int = 300      # 5 min
    onboarding_rate_max: int = 80     # llamadas de onboarding por ventana (las 3 rutas suman)
    onboarding_rate_window: int = 300

    # Web Push (avisos de vencimiento al celular). VAPID: la pública va al navegador,
    # la privada (archivo PEM) firma los envíos. Vacío = el push queda deshabilitado.
    vapid_public_key: str = ""
    vapid_private_key_file: str = "/opt/biblio/vapid_private.pem"
    vapid_subject: str = "mailto:admin@example.org"


settings = Settings()
