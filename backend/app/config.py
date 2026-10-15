"""Environment-driven settings for the CSR Outreach backend."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://csr_user:csr_password@localhost:5432/csr_outreach"
    cors_origins: str = "http://localhost:5173"
    hunter_api_key: str = ""
    apollo_api_key: str = ""

    # NGO profile (Phase 5 will turn this into a proper editable profile;
    # for now it's env-configured, matching this tool's single-NGO scope).
    ngo_name: str = "A Ray of Hope Foundation"
    ngo_work_area: str = "educating underprivileged children"
    ngo_focus_areas: str = "Education"
    ngo_city: str = "Pune"
    ngo_state: str = "Maharashtra"

    # Phase 3: AI features (lead-score explanations, email/summary/brief
    # generation). Optional - features report "not configured" without it.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Phase 6: upload caps, found missing during larger-volume testing -
    # without these, a single oversized file could exhaust the free-tier
    # backend's memory or bloat the Postgres row unbounded.
    max_document_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_csv_import_bytes: int = 5 * 1024 * 1024  # 5 MB

    # Real-company discovery (app/company_discovery/). Searches public
    # sources; nothing is stored in the database until "Save as lead".
    #
    # Wikidata: keyless, on by default. Wikimedia asks API clients to send
    # a descriptive User-Agent with a way to contact the operator - set
    # DISCOVERY_CONTACT to an email or URL for your deployment.
    discovery_contact: str = ""
    wikidata_enabled: bool = True
    wikidata_refresh_hours: int = 168  # rebuild the cached company index weekly
    # MCA company master data via the Open Government Data platform
    # (data.gov.in). Free key: register at https://data.gov.in and copy it
    # from "My Account". Leave blank to disable this source.
    data_gov_in_api_key: str = ""
    mca_resource_id: str = "4dbe5667-7b6b-41d7-82af-211562424d9a"
    # Official CSV files the NGO downloads itself (NSE/BSE lists, National
    # CSR Portal exports, MCA master data) - see datasets/README.md.
    # Relative paths resolve against the backend/ directory.
    discovery_datasets_dir: str = "datasets"
    discovery_cache_dir: str = ".cache"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ngo_focus_areas_list(self) -> list[str]:
        return [area.strip() for area in self.ngo_focus_areas.split(",") if area.strip()]


settings = Settings()
