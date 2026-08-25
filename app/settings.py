"""Runtime settings, loaded from environment via pydantic-settings."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="osint")
    postgres_user: str = Field(default="osint")
    postgres_password: str = Field(default="")

    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)

    fred_api_key: str = Field(default="")
    firms_map_key: str = Field(default="")
    acled_username: str = Field(default="")
    acled_password: str = Field(default="")
    acled_api_enabled: bool = Field(default=False)
    acled_csv_path: str = Field(default="")
    acled_csv_dir: str = Field(default="")
    emdat_csv_path: str = Field(default="")
    cyber_geo_enabled: bool = Field(default=True)
    cyber_geo_max_lookups: int = Field(default=25)

    pushover_token: str = Field(default="")
    pushover_user: str = Field(default="")

    # WS-G local LLM validator (#378) — localhost only, never a cloud API.
    ollama_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen3.5:4b-q4_K_M")
    validator_batch_limit: int = Field(default=200)
    # News severity grading (#591) had no setting of its own, so it rode on the
    # validator's model above and neither could move without the other. Split so
    # a bench result (#646) can swap the grader alone. Same default: this is a
    # seam, not a change — the #593 agreement still describes what runs.
    severity_model: str = Field(default="qwen3.5:4b-q4_K_M")

    # The brain (#409) — a light always-warm-when-idle local model, separate
    # from the 4b nightly validator above. Localhost only.
    brain_enabled: bool = Field(default=True)
    #: The question path only. `brain_enabled` above stops the whole brain —
    #: gists, tags, severity, the situation summary, the embeddings — and a
    #: small board wants every one of those; what it cannot afford is a
    #: user-triggered generation that takes minutes and holds the box while it
    #: runs. `make env` writes this false at 9 GB or less.
    #:
    #: `env.example` ships the key with no value, and has to. A key holding the
    #: value the example suggests is the example's answer rather than the
    #: operator's, and `scripts/env_setup.py` is allowed to write over exactly
    #: those — so an operator who turned questions back on by typing the same
    #: word the example printed would have it turned off again at the next
    #: `make env`. Blank is the only value that is unmistakably nobody's answer.
    ask_enabled: bool = Field(default=True)

    @field_validator("ask_enabled", mode="before")
    @classmethod
    def _blank_means_the_default(cls, value: object) -> object:
        """A key present with no value is the same as a key that is absent.

        Pydantic reads a bool from a small vocabulary and refuses everything
        else, blank included: `ASK_ENABLED=` in `.env` would otherwise stop the
        API from starting at all, with a validation error about a setting the
        operator never touched. It has to mean what the console's own reader
        already makes it mean — on — or the file the project ships would not
        boot the project.

        The refusal is kept for a word that is neither: `ASK_ENABLED=maybe` is
        a mistake worth failing loudly on, because guessing at it is how a
        console ends up drawing a control the API will refuse.
        """
        return True if isinstance(value, str) and not value.strip() else value

    # Moved off the 1.5b in #926. The tags it wrote were not merely sparse but
    # wrong — a total solar eclipse filed as a disaster, a missile strike on a
    # ship filed as a crime — and measurement said the model was the limit
    # rather than the prompt: on the same hand-checked stories the 1.5b scored
    # 3/7 and this scores 6/7, matching the 4b at roughly half its latency and
    # a little over half its memory. Bigger buys nothing here.
    brain_model: str = Field(default="llama3.2:3b")
    # Refuse to load the model unless at least this much RAM is free (box
    # guard). Measured resident at the num_ctx=8192 this code sends: the 1.5b
    # took 1.53 GB and this takes 3.40 GB, so the old 1200 MB floor would have
    # waved through a load with nowhere near room for it.
    brain_min_free_mb: int = Field(default=3500)
    brain_keep_alive: str = Field(default="30m")
    # How long the narrative may go unwritten before the heavy-job backoff
    # stops applying to it.
    #
    # The backoff is right on a laptop — do not load a model while something
    # else has the box — but it had no floor, and a job that yields to heavy
    # work yields forever on a machine where heavy work never stops. Measured
    # on a small board: five consecutive narrate beats refused, and the console
    # a reader opens showed nothing at all.
    #
    # Four missed beats at the 15-minute cadence. Shorter and one ordinary
    # overrun — a clustering run working through a backlog — would count as
    # starvation; longer and the page a reader opens is over an hour stale,
    # which is beyond what a page describing "now" can claim. On a laptop the
    # heavy beats finish in seconds and this never opens.
    brain_narrate_starvation_minutes: int = Field(default=60)
    # Q&A (#433): user asks run the 4b model per-ask and evict it right after —
    # the box never keeps two models resident. Narrative and enrichment stay on
    # the warm brain_model above.
    qa_model: str = Field(default="qwen3.5:4b-q4_K_M")
    qa_min_free_mb: int = Field(default=3800)
    # How many stories go into the Q&A prompt.
    #
    # On a machine with a GPU this barely shows: the prompt is processed in a
    # second or two, and six stories is a better answer than three — more
    # evidence in front of the model, more sources it can cite, more chance the
    # one the question is about is among them.
    #
    # Without a GPU the same tokens are the whole cost. Measured on a Raspberry
    # Pi: six stories is ~2,976 tokens and 1 m 48 s an ask, nearly all of it
    # processing the prompt rather than writing the answer. Sending fewer is the
    # cheaper trade than running a weaker model, because retrieval has already
    # ranked them and the ones dropped are the least relevant.
    qa_stories: int = Field(default=6)
    # How long Ollama holds the Q&A model after answering. "0" evicts it at once,
    # which is what the API did unconditionally — and on a small machine that
    # means every question reloads gigabytes from storage before generating a
    # token. Measured on a Raspberry Pi: the 4b took over three minutes to answer
    # "Say hello" that way, against the 120 s timeout below, and the console
    # reported the timeout as the brain being offline.
    #
    # Holding it briefly makes the second question onward cost generation only.
    # The price is its resident memory for that long, which is why this is a
    # setting and not a new hard-coded number — a laptop can afford to hold it, a
    # 4 GB box should still evict at once, and "0" keeps the old behaviour.
    qa_keep_alive: str = Field(default="0")
    # Whether Ollama runs in this machine's memory, when the code cannot tell.
    #
    # The RAM floors above only mean something if the reading describes the
    # machine that will hold the model. Reached over `host.docker.internal` that
    # is true on native Linux Docker, where the container shares the host kernel,
    # and false on Docker Desktop, where it is a virtual machine with its own few
    # gigabytes. The code decides by looking at the kernel; set this to override a
    # guess that is wrong on some arrangement nobody here has tried.
    brain_same_machine_as_ollama: bool | None = Field(default=None)
    # How long to wait for the model. Generous on a laptop, not always enough on a
    # small board loading a cold model, so it moves with the machine.
    brain_timeout_s: float = Field(default=120.0)
    # Semantic ask retrieval (#441): tiny local embedder, always keep_alive=0.
    embed_model: str = Field(default="nomic-embed-text")
    runtime_busy_lock_ttl_s: int = Field(default=1800)
    footprint_enrichment_limit: int = Field(default=25)
    # Courteous ceiling for the sequential Wikidata named-place pass (#745).
    # Positive and negative results persist, so repeat headlines cost no calls.
    place_enrichment_limit: int = Field(default=10)
    # Local read API caps. Large raw JSON pulls multiply memory across
    # Postgres, FastAPI, Next dev, browser state, and map render state.
    api_default_limit: int = Field(default=2000)
    api_max_limit: int = Field(default=10000)

    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    data_dir: str = Field(default="./data")

    retention_gdelt_days: int = Field(default=30)
    retention_news_days: int = Field(default=30)
    retention_hazard_days: int = Field(default=30)
    # Hard ceiling on DB disk use; oldest event-days are trimmed when exceeded.
    storage_cap_gb: int = Field(default=30)
    # Size-cap enforcement never deletes events newer than this many days.
    storage_cap_floor_days: int = Field(default=7)

    api_cors_origins: str = Field(default="http://localhost:3000,http://localhost:3001")
    #: Shared secret every endpoint but the liveness probe requires (#824).
    #: Empty means the API stays open, as it has been, and says so at startup.
    api_auth_token: str = Field(default="")

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


settings = Settings()
