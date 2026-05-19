from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


ClassStage = Literal["Class 11", "Class 12", "Repeater"]
AttemptYear = Literal[2027, 2028]
DailyStudyHours = Literal["1-2 hrs", "2-4 hrs", "4-6 hrs", "6+ hrs"]
Subject = Literal["Physics", "Chemistry", "Biology"]
ConfidenceLevel = Literal["Low", "Medium", "High"]
StudyTime = Literal["Morning", "Afternoon", "Evening", "Night"]


class PlanningAgentRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=80, description="UUID of the authenticated user")
    full_name: str = Field(..., min_length=1, max_length=120, examples=["Harish Gupta"])
    current_class_stage: ClassStage
    neet_attempt_year: AttemptYear
    daily_study_hours: DailyStudyHours
    strongest_subject: Subject
    weakest_subject: Subject
    self_confidence_level: ConfidenceLevel
    preferred_study_time: StudyTime


class StudyTask(BaseModel):
    subject: Subject
    chapter: str = Field(..., max_length=200)
    topic: str = Field(..., max_length=300)
    priority: str = Field(..., max_length=50)
    estimated_minutes: int
    activity: str = Field(..., max_length=500)


class DailyGeneratedTasks(BaseModel):
    date: date
    tasks: list[StudyTask]


class PlanMetadata(BaseModel):
    student_name: str
    current_class_stage: ClassStage
    neet_attempt_year: int
    neet_exam_date: date
    plan_start_date: date
    plan_end_date: date
    days_left: int
    daily_study_hours: DailyStudyHours
    preferred_study_time: StudyTime
    strongest_subject: Subject
    weakest_subject: Subject
    self_confidence_level: ConfidenceLevel
    generated_plan_days: int


class PlanningAgentResponse(BaseModel):
    plan_id: str
    metadata: PlanMetadata
    daily_schedule: list[DailyGeneratedTasks]
    ai_guidance: str
    storage_path: str
    warnings: list[str] = Field(default_factory=list)
