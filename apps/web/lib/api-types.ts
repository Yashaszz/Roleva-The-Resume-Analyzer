/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Produced from the FastAPI app's OpenAPI schema by scripts/gen-types.mjs.
 * The Pydantic models in apps/api are the source of truth; edit those and
 * re-run `pnpm gen:types`.
 */

export interface paths {
    "/analyze": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Analyze
         * @description Analyse one resume against one job description.
         *
         *     Synchronous. At fewer than a hundred analyses a day there is no queue worth
         *     running, and a request that returns the finished report is far simpler to
         *     reason about than a job id the client has to poll.
         */
        post: operations["analyze_analyze_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analyze/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Analyze Stream
         * @description The same analysis, with progress events while it runs.
         *
         *     Everything that can be rejected is rejected *before* the stream opens, so a
         *     quota error is still an HTTP 429 the client can handle normally. Once the
         *     first byte is sent the status is 200 for good, and any later failure has to
         *     travel as an error frame instead.
         */
        post: operations["analyze_stream_analyze_stream_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analyses": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Analyses
         * @description The signed-in user's analysis history, newest first.
         */
        get: operations["list_analyses_analyses_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/analyses/{analysis_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Analysis */
        get: operations["get_analysis_analyses__analysis_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Analysis
         * @description Delete an analysis permanently.
         *
         *     No soft delete. When somebody asks for their resume data to be removed, a
         *     row marked `deleted = true` is not removal.
         */
        delete: operations["delete_analysis_analyses__analysis_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/quota": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Quota Remaining
         * @description How many analyses the user has left today.
         *
         *     Read without incrementing — `bump_rate_limit` is the only thing that counts,
         *     and asking how many you have left must not spend one. The counter is written
         *     by that function and simply read here.
         */
        get: operations["quota_remaining_me_quota_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export My Data
         * @description Everything Roleva holds about this user, as JSON.
         *
         *     A data-export endpoint is only honest if it returns *everything*, so this
         *     reads every user-owned table rather than a curated subset. It runs with the
         *     caller's own token, so RLS decides what comes back — which means the export
         *     cannot accidentally include somebody else's row even if a filter were wrong.
         *
         *     `score_samples` is deliberately absent, and its absence is the point: those
         *     rows carry no user id, so there is nothing to attribute to anyone. Saying so
         *     here is more useful than silently omitting them.
         */
        get: operations["export_my_data_me_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Me
         * @description Confirms a token is valid. Returns the user id only — the backend has no
         *     reason to echo an email address back to a client that already has it.
         */
        get: operations["me_me_get"];
        put?: never;
        post?: never;
        /**
         * Delete My Account
         * @description Delete the account and everything attached to it.
         *
         *     Uses the service-role key, which is the one place a user-owned deletion
         *     legitimately needs it: removing a row from `auth.users` is an admin
         *     operation, and every table's foreign key cascades from there. So one call
         *     removes the profile, the resumes, the job targets, the analyses and the
         *     share links.
         *
         *     A real delete, not a flag. Someone asking for their resume data to be
         *     removed is not asking for a column to be set to true.
         */
        delete: operations["delete_my_account_me_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Liveness probe. Touches nothing, so it answers even when the DB is down.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/warmup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Warmup
         * @description Wake both free tiers before the user needs them.
         *
         *     Two things sleep, not one. Render suspends an idle instance and takes
         *     roughly fifty seconds to cold-start it; Supabase pauses an idle project and
         *     takes several seconds on its first query. A health check that touches no
         *     database wakes only half of what an analysis needs.
         *
         *     So this also runs the cheapest possible query. The frontend calls it the
         *     moment somebody lands on the upload page — during the sixty-odd seconds they
         *     spend choosing a file and pasting a job description, which is exactly the
         *     window both services need.
         *
         *     Unauthenticated on purpose: requiring a token would mean the wake-up could
         *     not happen until after sign-in, which is most of the wait it exists to
         *     remove. It reads no rows and reveals nothing.
         */
        get: operations["warmup_warmup_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AnalysisReport */
        AnalysisReport: {
            /**
             * Schema Version
             * @default 1
             */
            schema_version: number;
            /** Id */
            id: string;
            status: components["schemas"]["AnalysisStatus"];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            resume: components["schemas"]["ResumeDocument"];
            job: components["schemas"]["JobTarget"];
            matches: components["schemas"]["MatchReport"];
            ats: components["schemas"]["AtsReport"];
            scores: components["schemas"]["ScoreReport"];
            /**
             * Headline
             * @default
             */
            headline: string;
            /**
             * Verdict
             * @default
             */
            verdict: string;
            /** Strengths */
            strengths?: string[];
            /** Weaknesses */
            weaknesses?: string[];
            /** Section Feedback */
            section_feedback?: components["schemas"]["SectionFeedback"][];
            /** Bullet Suggestions */
            bullet_suggestions?: components["schemas"]["BulletSuggestion"][];
            /** Recommendations */
            recommendations?: components["schemas"]["Recommendation"][];
            /** Rubric Version */
            rubric_version: string;
            /** Prompt Version */
            prompt_version: string;
            /** Degraded Stages */
            degraded_stages?: components["schemas"]["Stage"][];
        };
        /**
         * AnalysisStatus
         * @enum {string}
         */
        AnalysisStatus: "pending" | "running" | "complete" | "partial" | "failed";
        /** AtsFinding */
        AtsFinding: {
            rule_id: components["schemas"]["AtsRuleId"];
            severity: components["schemas"]["AtsSeverity"];
            /** Deduction */
            deduction: number;
            /** Title */
            title: string;
            /** Detail */
            detail: string;
            /** Fix */
            fix: string;
            /**
             * Page
             * @default null
             */
            page: number | null;
            /**
             * Occurrences
             * @default 1
             */
            occurrences: number;
        };
        /** AtsReport */
        AtsReport: {
            /** Findings */
            findings?: components["schemas"]["AtsFinding"][];
            /**
             * Hidden Text Detected
             * @default false
             */
            hidden_text_detected: boolean;
            /**
             * Checks Run
             * @default 0
             */
            checks_run: number;
        };
        /**
         * AtsRuleId
         * @enum {string}
         */
        AtsRuleId: "ats.multi_column" | "ats.text_in_table" | "ats.text_as_image" | "ats.content_in_header_footer" | "ats.no_standard_sections" | "ats.missing_experience" | "ats.missing_education" | "ats.missing_email" | "ats.missing_phone" | "ats.unparseable_dates" | "ats.exotic_fonts" | "ats.hidden_text" | "ats.informative_graphics" | "ats.excessive_length" | "ats.special_chars_in_headers" | "ats.unprofessional_filename";
        /**
         * AtsSeverity
         * @enum {string}
         */
        AtsSeverity: "critical" | "major" | "minor";
        /**
         * Band
         * @enum {string}
         */
        Band: "strong" | "competitive" | "needs_work" | "significant_gaps" | "not_aligned";
        /** Body_analyze_analyze_post */
        Body_analyze_analyze_post: {
            /**
             * File
             * @description The resume, as a PDF
             */
            file: string;
            /**
             * Job Description
             * @description The full job posting text
             */
            job_description: string;
        };
        /** Body_analyze_stream_analyze_stream_post */
        Body_analyze_stream_analyze_stream_post: {
            /**
             * File
             * @description The resume, as a PDF
             */
            file: string;
            /**
             * Job Description
             * @description The full job posting text
             */
            job_description: string;
        };
        /** Bullet */
        Bullet: {
            /** Id */
            id?: string;
            /** Text */
            text: string;
            /** @default null */
            span: components["schemas"]["Span"] | null;
        };
        /**
         * BulletSuggestion
         * @description A concrete improvement for one weak bullet.
         *
         *     Grounding rule: the suggestion may not introduce facts (numbers, employers,
         *     technologies) absent from `original`. Violations are regenerated once, then
         *     dropped.
         */
        BulletSuggestion: {
            /** Bullet Id */
            bullet_id: string;
            /** Original */
            original: string;
            /** Suggestion */
            suggestion: string;
            /** Reasons */
            reasons?: string[];
            section: components["schemas"]["SectionKind"];
        };
        /**
         * ContactInfo
         * @description Populated by deterministic extraction. Feeds the PII redactor — every
         *     value here is masked before any text is sent to an external LLM.
         */
        ContactInfo: {
            /**
             * Name
             * @default null
             */
            name: string | null;
            /**
             * Email
             * @default null
             */
            email: string | null;
            /**
             * Phone
             * @default null
             */
            phone: string | null;
            /**
             * Location
             * @default null
             */
            location: string | null;
            /** Links */
            links?: string[];
        };
        /**
         * CredentialItem
         * @description Certifications, awards, publications — same shape, different section.
         */
        CredentialItem: {
            /** Id */
            id?: string;
            /** Title */
            title: string;
            /**
             * Issuer
             * @default null
             */
            issuer: string | null;
            dates?: components["schemas"]["DateRange"];
            /** @default null */
            span: components["schemas"]["Span"] | null;
        };
        /**
         * DateRange
         * @description Employment/education dates. Always parsed deterministically in Python —
         *     never taken from an LLM, which is unreliable at date arithmetic.
         */
        DateRange: {
            /**
             * Start Year
             * @default null
             */
            start_year: number | null;
            /**
             * Start Month
             * @default null
             */
            start_month: number | null;
            /**
             * End Year
             * @default null
             */
            end_year: number | null;
            /**
             * End Month
             * @default null
             */
            end_month: number | null;
            /**
             * Is Current
             * @default false
             */
            is_current: boolean;
            /**
             * Raw
             * @default null
             */
            raw: string | null;
        };
        /**
         * DetectedSection
         * @description A heading found in the source document, with its text range.
         */
        DetectedSection: {
            /** Id */
            id?: string;
            kind: components["schemas"]["SectionKind"];
            /**
             * Heading Text
             * @default null
             */
            heading_text: string | null;
            /**
             * Order
             * @default 0
             */
            order: number;
            /** @default null */
            span: components["schemas"]["Span"] | null;
            /**
             * Heading Confidence
             * @default 1
             */
            heading_confidence: number;
        };
        /** EducationItem */
        EducationItem: {
            /** Id */
            id?: string;
            /**
             * Degree
             * @default null
             */
            degree: string | null;
            /**
             * Field Of Study
             * @default null
             */
            field_of_study: string | null;
            /**
             * Institution
             * @default null
             */
            institution: string | null;
            /**
             * Location
             * @default null
             */
            location: string | null;
            dates?: components["schemas"]["DateRange"];
            /**
             * Gpa
             * @default null
             */
            gpa: string | null;
            /** Bullets */
            bullets?: components["schemas"]["Bullet"][];
            /** @default null */
            span: components["schemas"]["Span"] | null;
        };
        /**
         * Evidence
         * @description One piece of support for a requirement, anchored in the resume text.
         *
         *     Invariant: `span.verify(resume_text)` must pass before this is shown to a
         *     user. Unverifiable evidence is dropped, which makes hallucinated evidence
         *     structurally impossible to display.
         */
        Evidence: {
            span: components["schemas"]["Span"];
            origin: components["schemas"]["SkillOrigin"];
            provenance: components["schemas"]["Provenance"];
            /**
             * Similarity
             * @default null
             */
            similarity: number | null;
            /**
             * Note
             * @default null
             */
            note: string | null;
        };
        /**
         * ExpectedBand
         * @description Reference range for a role family + seniority. Curated, not measured —
         *     always labelled as a "typical range", never as a percentile.
         */
        ExpectedBand: {
            kind: components["schemas"]["ScoreKind"];
            /** Low */
            low: number;
            /** High */
            high: number;
            /** Position */
            position: string;
        };
        /** ExperienceItem */
        ExperienceItem: {
            /** Id */
            id?: string;
            /**
             * Title
             * @default null
             */
            title: string | null;
            /**
             * Organization
             * @default null
             */
            organization: string | null;
            /**
             * Location
             * @default null
             */
            location: string | null;
            dates?: components["schemas"]["DateRange"];
            /** Bullets */
            bullets?: components["schemas"]["Bullet"][];
            /** @default null */
            span: components["schemas"]["Span"] | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * JobTarget
         * @description A parsed job description.
         */
        JobTarget: {
            /**
             * Schema Version
             * @default 1
             */
            schema_version: number;
            /**
             * Title
             * @default null
             */
            title: string | null;
            /**
             * Company
             * @default null
             */
            company: string | null;
            /**
             * Role Family
             * @default general
             */
            role_family: string;
            /** @default unknown */
            seniority: components["schemas"]["Seniority"];
            /** Requirements */
            requirements?: components["schemas"]["Requirement"][];
            /** Warnings */
            warnings?: string[];
        };
        /** MatchReport */
        MatchReport: {
            /** Matches */
            matches?: components["schemas"]["RequirementMatch"][];
            /** Unmatched Resume Skills */
            unmatched_resume_skills?: string[];
            /**
             * Llm Adjudicated Count
             * @default 0
             */
            llm_adjudicated_count: number;
        };
        /**
         * MatchStatus
         * @enum {string}
         */
        MatchStatus: "matched" | "partial" | "missing";
        /**
         * Percentile
         * @description True cohort percentile. Only populated once `sample_size` >= 30; below
         *     that the UI must show nothing rather than a fabricated statistic.
         */
        Percentile: {
            kind: components["schemas"]["ScoreKind"];
            /** Percentile */
            percentile: number;
            /** Sample Size */
            sample_size: number;
            /** Role Family */
            role_family: string;
            /** Seniority */
            seniority: string;
        };
        /**
         * Priority
         * @enum {string}
         */
        Priority: "must" | "strong" | "nice";
        /** ProjectItem */
        ProjectItem: {
            /** Id */
            id?: string;
            /**
             * Name
             * @default null
             */
            name: string | null;
            /**
             * Description
             * @default null
             */
            description: string | null;
            /** Technologies */
            technologies?: string[];
            dates?: components["schemas"]["DateRange"];
            /** Bullets */
            bullets?: components["schemas"]["Bullet"][];
            /**
             * Link
             * @default null
             */
            link: string | null;
            /** @default null */
            span: components["schemas"]["Span"] | null;
        };
        /**
         * Provenance
         * @description How a claim was produced. Rendered in the UI so users can weigh it.
         * @enum {string}
         */
        Provenance: "rule" | "computed" | "lexical" | "semantic" | "judged" | "extracted";
        /**
         * Quantifier
         * @description A numeric threshold attached to a requirement, e.g. "3+ years".
         */
        Quantifier: {
            /**
             * Years
             * @default null
             */
            years: number | null;
            /**
             * Raw
             * @default null
             */
            raw: string | null;
        };
        /** Recommendation */
        Recommendation: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /** Detail */
            detail: string;
            severity: components["schemas"]["Severity"];
            /**
             * Projected Gain
             * @default 0
             */
            projected_gain: number;
            /** Related Requirement Ids */
            related_requirement_ids?: string[];
        };
        /** Requirement */
        Requirement: {
            /** Id */
            id?: string;
            /** Text */
            text: string;
            /**
             * Canonical
             * @default null
             */
            canonical: string | null;
            category: components["schemas"]["RequirementCategory"];
            priority: components["schemas"]["Priority"];
            /** @default extracted */
            priority_source: components["schemas"]["Provenance"];
            /** @default null */
            quantifier: components["schemas"]["Quantifier"] | null;
            /**
             * Mention Count
             * @default 1
             */
            mention_count: number;
            /** @default null */
            span: components["schemas"]["Span"] | null;
        };
        /**
         * RequirementCategory
         * @enum {string}
         */
        RequirementCategory: "hard_skill" | "tool" | "soft_skill" | "experience" | "education" | "certification" | "domain" | "responsibility";
        /**
         * RequirementMatch
         * @description The resolved outcome for a single JD requirement.
         */
        RequirementMatch: {
            /** Requirement Id */
            requirement_id: string;
            status: components["schemas"]["MatchStatus"];
            /** Strength */
            strength: number;
            /** Evidence */
            evidence?: components["schemas"]["Evidence"][];
            /**
             * Is Adjacent
             * @default false
             */
            is_adjacent: boolean;
            /**
             * Observed Months
             * @default null
             */
            observed_months: number | null;
            /**
             * Explanation
             * @default null
             */
            explanation: string | null;
        };
        /**
         * ResumeDocument
         * @description The structured resume. Analyzer reads it; the future builder will edit it.
         */
        ResumeDocument: {
            /**
             * Schema Version
             * @default 1
             */
            schema_version: number;
            contact?: components["schemas"]["ContactInfo"];
            /** @default null */
            summary: components["schemas"]["Bullet"] | null;
            /** Experience */
            experience?: components["schemas"]["ExperienceItem"][];
            /** Education */
            education?: components["schemas"]["EducationItem"][];
            /** Projects */
            projects?: components["schemas"]["ProjectItem"][];
            /** Skills */
            skills?: components["schemas"]["SkillMention"][];
            /** Certifications */
            certifications?: components["schemas"]["CredentialItem"][];
            /** Awards */
            awards?: components["schemas"]["CredentialItem"][];
            /** Publications */
            publications?: components["schemas"]["CredentialItem"][];
            /** Sections */
            sections?: components["schemas"]["DetectedSection"][];
            /**
             * Page Count
             * @default 0
             */
            page_count: number;
            /**
             * Parse Confidence
             * @default 0
             */
            parse_confidence: number;
            /** Parse Warnings */
            parse_warnings?: string[];
        };
        /** Score */
        Score: {
            kind: components["schemas"]["ScoreKind"];
            /** Value */
            value: number;
            band: components["schemas"]["Band"];
            /** Components */
            components?: components["schemas"]["ScoreComponent"][];
            /**
             * Cap Applied
             * @default null
             */
            cap_applied: string | null;
            /**
             * Uncapped Value
             * @default null
             */
            uncapped_value: number | null;
            /**
             * Confidence
             * @default 1
             */
            confidence: number;
        };
        /**
         * ScoreComponent
         * @description One contributing factor, with its arithmetic exposed.
         */
        ScoreComponent: {
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Contribution */
            contribution: number;
            /**
             * Weight
             * @default null
             */
            weight: number | null;
            /**
             * Raw Value
             * @default null
             */
            raw_value: number | null;
            provenance: components["schemas"]["Provenance"];
            /**
             * Detail
             * @default null
             */
            detail: string | null;
            /** Evidence Refs */
            evidence_refs?: string[];
        };
        /**
         * ScoreKind
         * @enum {string}
         */
        ScoreKind: "overall" | "job_match" | "ats" | "quality";
        /** ScoreReport */
        ScoreReport: {
            overall: components["schemas"]["Score"];
            job_match: components["schemas"]["Score"];
            ats: components["schemas"]["Score"];
            quality: components["schemas"]["Score"];
            /** Must Coverage */
            must_coverage: number;
            /** Overall Coverage */
            overall_coverage: number;
            /** Expected Bands */
            expected_bands?: components["schemas"]["ExpectedBand"][];
            /** Percentiles */
            percentiles?: components["schemas"]["Percentile"][];
            /** Rubric Version */
            rubric_version: string;
        };
        /** SectionFeedback */
        SectionFeedback: {
            section: components["schemas"]["SectionKind"];
            /** Rating */
            rating: number;
            /** Strengths */
            strengths?: string[];
            /** Issues */
            issues?: string[];
        };
        /**
         * SectionKind
         * @description Canonical section types. Unrecognized headings map to OTHER.
         * @enum {string}
         */
        SectionKind: "contact" | "summary" | "experience" | "education" | "skills" | "projects" | "certifications" | "awards" | "publications" | "volunteer" | "languages" | "interests" | "other";
        /**
         * Seniority
         * @enum {string}
         */
        Seniority: "intern" | "entry" | "mid" | "senior" | "unknown";
        /**
         * Severity
         * @enum {string}
         */
        Severity: "high" | "medium" | "low";
        /** SkillMention */
        SkillMention: {
            /** Id */
            id?: string;
            /** Raw */
            raw: string;
            /**
             * Canonical
             * @default null
             */
            canonical: string | null;
            /** @default other */
            origin: components["schemas"]["SkillOrigin"];
            /** @default null */
            span: components["schemas"]["Span"] | null;
        };
        /**
         * SkillOrigin
         * @description Where a skill was found. Drives evidence strength during matching:
         *     a skill demonstrated in a bullet is worth far more than one merely listed.
         * @enum {string}
         */
        SkillOrigin: "skills_list" | "experience_bullet" | "project_bullet" | "summary" | "education" | "certification" | "other";
        /**
         * SourceDoc
         * @enum {string}
         */
        SourceDoc: "resume" | "job_description";
        /**
         * Span
         * @description A character range in a normalized source document.
         */
        Span: {
            doc: components["schemas"]["SourceDoc"];
            /** Start */
            start: number;
            /** End */
            end: number;
            /** Text */
            text: string;
            /**
             * Page
             * @default null
             */
            page: number | null;
            /**
             * Section Id
             * @default null
             */
            section_id: string | null;
        };
        /**
         * Stage
         * @description Pipeline stages. Names are user-visible in the progress UI, so they
         *     describe work the user cares about, not internal function names.
         * @enum {string}
         */
        Stage: "validating" | "extracting" | "structuring" | "reading_job" | "matching" | "checking_ats" | "assessing_quality" | "scoring" | "writing_advice" | "done";
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /**
         * ProgressEvent
         * @description One SSE frame. The progress screen is a designed experience, not a
         *     spinner, so events carry real stage names and optional partial results.
         */
        ProgressEvent: {
            /** Analysis Id */
            analysis_id: string;
            stage: components["schemas"]["Stage"];
            /** Message */
            message: string;
            /** Percent */
            percent: number;
            /**
             * Partial
             * @default null
             */
            partial: {
                [key: string]: unknown;
            } | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    analyze_analyze_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_analyze_analyze_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalysisReport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    analyze_stream_analyze_stream_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_analyze_stream_analyze_stream_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_analyses_analyses_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_analysis_analyses__analysis_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                analysis_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalysisReport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_analysis_analyses__analysis_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                analysis_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    quota_remaining_me_quota_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    export_my_data_me_export_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    me_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    delete_my_account_me_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    warmup_warmup_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
}
