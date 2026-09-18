/**
 * Friendly aliases over the generated API types.
 *
 * Components import from here rather than reaching into `api-types.ts`, so the
 * generated file's shape (`components["schemas"][...]`) stays an implementation
 * detail. If the generator changes, this is the only file that has to adapt.
 */

import type { components } from "./api-types";

type Schemas = components["schemas"];

// --- resume ---
export type ResumeDocument = Schemas["ResumeDocument"];
export type ExperienceItem = Schemas["ExperienceItem"];
export type EducationItem = Schemas["EducationItem"];
export type ProjectItem = Schemas["ProjectItem"];
export type SkillMention = Schemas["SkillMention"];
export type Bullet = Schemas["Bullet"];
export type ContactInfo = Schemas["ContactInfo"];
export type SectionKind = Schemas["SectionKind"];
export type SkillOrigin = Schemas["SkillOrigin"];

// --- job ---
export type JobTarget = Schemas["JobTarget"];
export type Requirement = Schemas["Requirement"];
export type Priority = Schemas["Priority"];
export type RequirementCategory = Schemas["RequirementCategory"];
export type Seniority = Schemas["Seniority"];

// --- matching ---
export type MatchReport = Schemas["MatchReport"];
export type RequirementMatch = Schemas["RequirementMatch"];
export type MatchStatus = Schemas["MatchStatus"];
export type Evidence = Schemas["Evidence"];
export type Span = Schemas["Span"];
export type Provenance = Schemas["Provenance"];

// --- ats ---
export type AtsReport = Schemas["AtsReport"];
export type AtsFinding = Schemas["AtsFinding"];
export type AtsSeverity = Schemas["AtsSeverity"];

// --- scoring ---
export type ScoreReport = Schemas["ScoreReport"];
export type Score = Schemas["Score"];
export type ScoreComponent = Schemas["ScoreComponent"];
export type ScoreKind = Schemas["ScoreKind"];
export type Band = Schemas["Band"];
export type ExpectedBand = Schemas["ExpectedBand"];
export type Percentile = Schemas["Percentile"];

// --- report ---
export type AnalysisReport = Schemas["AnalysisReport"];
export type AnalysisStatus = Schemas["AnalysisStatus"];
export type Recommendation = Schemas["Recommendation"];
export type BulletSuggestion = Schemas["BulletSuggestion"];
export type SectionFeedback = Schemas["SectionFeedback"];
export type ProgressEvent = Schemas["ProgressEvent"];
export type Stage = Schemas["Stage"];
export type Severity = Schemas["Severity"];
