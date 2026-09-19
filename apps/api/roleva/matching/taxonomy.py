"""Skill taxonomy and alias resolution.

Resumes and job descriptions name the same thing differently: `k8s` and
`Kubernetes`, `JS` and `JavaScript`, `Postgres` and `PostgreSQL`. Without a
canonical form, a candidate who lists `Node` fails a requirement for `Node.js`,
which is both wrong and the kind of wrongness a user notices immediately.

This is tier one of the matching cascade and resolves the large majority of
requirements at no cost — no embeddings, no model call. On a
request-limited free tier, every requirement settled here is one that does not
consume quota.

Adjacency is kept separate from equivalence. Vue is not React, and recording
them as the same skill would let Roleva tell someone they match a requirement
they do not. Adjacent skills earn partial credit and say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

#: canonical name -> every way it is written. Canonical forms are the spelling
#: a job description would normally use.
ALIASES: dict[str, tuple[str, ...]] = {
    # --- languages ---
    "Python": ("python3", "python 3", "py"),
    "JavaScript": ("js", "java script", "ecmascript", "es6", "es2015"),
    "TypeScript": ("ts",),
    "Java": ("java se", "java ee", "core java", "j2ee"),
    "C++": ("cpp", "c plus plus", "cplusplus"),
    "C#": ("c sharp", "csharp", "dotnet c#"),
    "Go": ("golang",),
    "Ruby": (),
    "PHP": (),
    "Swift": (),
    "Kotlin": (),
    "Rust": (),
    "Scala": (),
    "R": ("r language", "r programming"),
    "MATLAB": ("matlab",),
    "SQL": ("structured query language",),
    "Bash": ("shell scripting", "shell", "sh", "zsh"),
    "HTML": ("html5",),
    "CSS": ("css3",),
    # --- web frontend ---
    "React": ("react.js", "reactjs", "react js"),
    "Next.js": ("nextjs", "next js", "next"),
    "Vue.js": ("vue", "vuejs", "vue js"),
    "Angular": ("angularjs", "angular.js", "angular 2+"),
    "Svelte": ("sveltekit",),
    "Redux": ("redux toolkit", "rtk"),
    "Tailwind CSS": ("tailwind", "tailwindcss"),
    "Bootstrap": (),
    "jQuery": ("jquery",),
    "Webpack": (),
    "Vite": (),
    # --- backend ---
    "Node.js": ("node", "nodejs", "node js"),
    "Express.js": ("express", "expressjs"),
    "Django": ("django rest framework", "drf"),
    "Flask": (),
    "FastAPI": ("fast api",),
    "Spring Boot": ("springboot", "spring"),
    "Ruby on Rails": ("rails", "ror"),
    "Laravel": (),
    ".NET": ("dotnet", "asp.net", "asp net", ".net core"),
    "GraphQL": ("graph ql",),
    "REST APIs": ("rest", "restful", "restful apis", "rest api", "api development"),
    "gRPC": ("grpc",),
    "Microservices": ("micro services", "microservice architecture"),
    # --- data stores ---
    "PostgreSQL": ("postgres", "psql", "postgre sql"),
    "MySQL": ("my sql", "mariadb"),
    "MongoDB": ("mongo",),
    "Redis": (),
    "Elasticsearch": ("elastic search", "elk", "opensearch"),
    "Cassandra": (),
    "DynamoDB": ("dynamo db",),
    "SQLite": ("sqlite3",),
    "Snowflake": (),
    "BigQuery": ("big query",),
    "Redshift": (),
    # --- cloud and infrastructure ---
    "AWS": ("amazon web services", "aws cloud"),
    "Azure": ("microsoft azure",),
    "GCP": ("google cloud", "google cloud platform"),
    "Docker": ("containerisation", "containerization", "containers"),
    "Kubernetes": ("k8s", "kube", "eks", "gke", "aks"),
    "Terraform": ("hashicorp terraform",),
    "Ansible": (),
    "Jenkins": (),
    "GitHub Actions": ("github action", "gh actions"),
    "GitLab CI": ("gitlab ci/cd", "gitlab pipelines"),
    "CI/CD": ("ci cd", "continuous integration", "continuous deployment", "cicd"),
    "Linux": ("unix", "ubuntu", "debian", "centos"),
    "Nginx": (),
    "Serverless": ("lambda", "aws lambda", "cloud functions"),
    "Prometheus": (),
    "Grafana": (),
    "Kafka": ("apache kafka",),
    "RabbitMQ": ("rabbit mq",),
    "Airflow": ("apache airflow",),
    "Spark": ("apache spark", "pyspark"),
    "Hadoop": (),
    # --- data and ML ---
    "pandas": ("pandas library",),
    "NumPy": ("numpy",),
    "scikit-learn": ("sklearn", "scikit learn", "sci-kit learn"),
    "PyTorch": ("pytorch", "torch"),
    "TensorFlow": ("tensorflow", "tf", "keras"),
    "Machine Learning": ("ml", "machine-learning", "statistical learning"),
    "Deep Learning": ("neural networks", "dl"),
    "NLP": ("natural language processing",),
    "Computer Vision": ("cv", "image processing"),
    "Data Analysis": ("data analytics", "analytics"),
    "Data Visualization": ("data visualisation", "dataviz"),
    "Statistics": ("statistical analysis", "stats"),
    "A/B Testing": ("ab testing", "split testing", "experimentation"),
    "ETL": ("etl pipelines", "elt", "data pipelines"),
    "dbt": ("data build tool",),
    "MLflow": ("ml flow",),
    "Time Series": ("time-series", "forecasting", "arima", "prophet"),
    # --- BI and office ---
    "Tableau": (),
    "Power BI": ("powerbi", "power-bi", "microsoft power bi"),
    "Looker": ("looker studio",),
    "Excel": ("microsoft excel", "ms excel", "advanced excel", "spreadsheets"),
    "Google Sheets": ("sheets",),
    "PowerPoint": ("microsoft powerpoint", "ms powerpoint", "slides"),
    # --- design ---
    "Figma": (),
    "Adobe XD": ("adobe experience design", "xd"),
    "Sketch": (),
    "Photoshop": ("adobe photoshop", "ps"),
    "Illustrator": ("adobe illustrator", "ai"),
    "InVision": (),
    "Prototyping": ("prototypes", "rapid prototyping"),
    "Wireframing": ("wireframes",),
    "User Research": ("ux research", "usability research"),
    "Usability Testing": ("user testing",),
    "Design Systems": ("design system", "component library"),
    "Accessibility": ("a11y", "wcag", "web accessibility", "ada compliance"),
    "Interaction Design": ("ixd",),
    "Information Architecture": ("ia",),
    "Motion Design": ("motion graphics", "animation"),
    # --- testing and quality ---
    "Unit Testing": ("unit tests", "pytest", "junit", "jest"),
    "Integration Testing": ("integration tests",),
    "Selenium": (),
    "Cypress": (),
    "Playwright": (),
    "Postman": (),
    "Test Automation": ("automated testing", "automation testing", "qa automation"),
    "Manual Testing": ("manual qa", "exploratory testing"),
    "ISTQB": (),
    "Test Planning": ("test plans", "test cases", "test design"),
    # --- tools and process ---
    "Git": ("version control", "git version control"),
    "GitHub": (),
    "GitLab": (),
    "Bitbucket": (),
    "Jira": ("atlassian jira",),
    "Confluence": (),
    "Agile": ("agile methodology", "agile development"),
    "Scrum": ("scrum master",),
    "Kanban": (),
    "Notion": (),
    "Slack": (),
    "Amplitude": (),
    "Mixpanel": (),
    "Google Analytics": ("ga", "ga4"),
    "Visio": ("microsoft visio",),
    "Lucidchart": ("lucid chart",),
    # --- product and business ---
    "Product Management": ("product owner", "product strategy"),
    "Requirements Gathering": ("requirement gathering", "requirements elicitation"),
    "Stakeholder Management": ("stakeholder engagement",),
    "Roadmapping": ("product roadmap", "roadmap planning"),
    "Competitive Analysis": ("market analysis", "competitor analysis"),
    "Process Mapping": ("process modelling", "process modeling", "bpmn"),
    "Financial Modelling": ("financial modeling", "financial models"),
    "Business Analysis": ("business analyst",),
    "User Acceptance Testing": ("uat",),
    "Project Management": ("project delivery", "pmp"),
    # --- soft skills ---
    "Written Communication": ("writing", "written communications", "technical writing"),
    "Verbal Communication": ("verbal communications", "presentation skills", "presenting"),
    "Communication": ("communication skills", "communicating"),
    "Collaboration": ("teamwork", "working in teams", "cross-functional collaboration"),
    "Problem Solving": ("problem-solving", "analytical thinking", "critical thinking"),
    "Attention to Detail": ("detail oriented", "detail-oriented", "meticulous"),
    "Leadership": ("leading teams", "team leadership"),
    "Mentoring": ("mentorship", "coaching"),
    "Ownership": ("taking ownership", "self-starter", "autonomy", "independently"),
    "Time Management": ("prioritisation", "prioritization"),
    # --- domain ---
    "Payments": ("payment systems", "payment processing", "pci dss"),
    "Healthcare": ("health tech", "clinical", "hipaa"),
    "E-commerce": ("ecommerce", "retail tech"),
    "Logistics": ("supply chain", "fulfilment", "fulfillment"),
    "Fintech": ("financial services", "banking"),
    "Bioinformatics": ("computational biology", "genomics"),
    "Security": ("cybersecurity", "information security", "infosec", "appsec"),
    # --- education ---
    "Bachelor's Degree": (
        "bachelors",
        "bachelor degree",
        "b.tech",
        "btech",
        "b.e.",
        "bsc",
        "b.sc",
        "undergraduate degree",
        "ba",
        "bs",
    ),
    "Master's Degree": ("masters", "master degree", "m.tech", "mtech", "msc", "m.sc", "ms"),
    "PhD": ("doctorate", "ph.d", "doctoral"),
    "Computer Science": ("cs", "comp sci", "computer engineering"),
    "Portfolio": ("design portfolio", "portfolio of work"),
}

#: Skills that are related but NOT the same. Earns partial credit, never a
#: full match: telling someone they satisfy a React requirement because they
#: know Vue would be a lie they might act on.
ADJACENT: dict[str, tuple[str, ...]] = {
    "React": ("Vue.js", "Angular", "Svelte"),
    "Vue.js": ("React", "Angular", "Svelte"),
    "Angular": ("React", "Vue.js"),
    "Svelte": ("React", "Vue.js"),
    "PostgreSQL": ("MySQL", "SQLite", "MongoDB"),
    "MySQL": ("PostgreSQL", "SQLite"),
    "AWS": ("Azure", "GCP"),
    "Azure": ("AWS", "GCP"),
    "GCP": ("AWS", "Azure"),
    "PyTorch": ("TensorFlow",),
    "TensorFlow": ("PyTorch",),
    "Django": ("Flask", "FastAPI"),
    "Flask": ("Django", "FastAPI"),
    "FastAPI": ("Flask", "Django"),
    "Tableau": ("Power BI", "Looker"),
    "Power BI": ("Tableau", "Looker"),
    "Looker": ("Tableau", "Power BI"),
    "Java": ("C#", "Kotlin"),
    "C#": ("Java",),
    "Kafka": ("RabbitMQ",),
    "RabbitMQ": ("Kafka",),
    "Jenkins": ("GitHub Actions", "GitLab CI"),
    "GitHub Actions": ("Jenkins", "GitLab CI"),
    "Selenium": ("Cypress", "Playwright"),
    "Cypress": ("Selenium", "Playwright"),
    "Playwright": ("Selenium", "Cypress"),
    "Figma": ("Sketch", "Adobe XD"),
    "Sketch": ("Figma", "Adobe XD"),
    "Adobe XD": ("Figma", "Sketch"),
}

#: Fuzzy matches at or above this are accepted as the same skill. High enough
#: that "Java" and "JavaScript" stay distinct, which a looser threshold breaks.
FUZZY_THRESHOLD = 88

_PUNCT = re.compile(r"[^\w\s+#.]")
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase and strip punctuation, keeping the characters that carry
    meaning in skill names: C++, C#, .NET, Next.js."""
    cleaned = _PUNCT.sub(" ", text.lower())
    return _SPACES.sub(" ", cleaned).strip()


def _build_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        lookup[normalise(canonical)] = canonical
        for alias in aliases:
            lookup[normalise(alias)] = canonical
    return lookup


_LOOKUP = _build_lookup()

#: Longest first, so "machine learning" is not matched as "learning".
_SORTED_TERMS: tuple[str, ...] = tuple(sorted(_LOOKUP, key=len, reverse=True))


@dataclass(frozen=True)
class Resolution:
    canonical: str
    matched_alias: str
    exact: bool
    score: float = 100.0


def resolve(text: str) -> Resolution | None:
    """Map a written skill onto its canonical form.

    Exact alias lookup first, then fuzzy matching for typos and spacing. Both
    are cheap; between them they settle most requirements without a model.
    """
    key = normalise(text)
    if not key:
        return None

    canonical = _LOOKUP.get(key)
    if canonical is not None:
        return Resolution(canonical=canonical, matched_alias=key, exact=True)

    best: tuple[str, float] | None = None
    for term in _SORTED_TERMS:
        # Length guard: without it "R" fuzzy-matches half the taxonomy.
        if abs(len(term) - len(key)) > max(4, len(key) * 0.5):
            continue
        score = fuzz.token_sort_ratio(key, term)
        if score >= FUZZY_THRESHOLD and (best is None or score > best[1]):
            best = (term, score)

    if best is None:
        return None

    return Resolution(canonical=_LOOKUP[best[0]], matched_alias=best[0], exact=False, score=best[1])


def find_in_text(text: str) -> list[tuple[str, int, int]]:
    """Every canonical skill named in a body of text, with its position.

    Longest-term-first so "Machine Learning" is found as one skill rather than
    two, and word-boundary anchored so "R" does not match every word containing
    the letter.
    """
    haystack = normalise(text)
    found: list[tuple[str, int, int]] = []
    claimed: list[tuple[int, int]] = []

    for term in _SORTED_TERMS:
        for match in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", haystack):
            start, end = match.span()
            if any(start < taken_end and end > taken_start for taken_start, taken_end in claimed):
                continue
            claimed.append((start, end))
            found.append((_LOOKUP[term], start, end))

    return sorted(found, key=lambda item: item[1])


def is_adjacent(requirement: str, candidate: str) -> bool:
    """Whether two canonical skills are related without being the same."""
    return candidate in ADJACENT.get(requirement, ())


def canonical_names() -> tuple[str, ...]:
    return tuple(ALIASES)
