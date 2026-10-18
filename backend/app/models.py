from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Model):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class UserCreate(Model):
    username: str = Field(min_length=2, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=200)
    role: Literal['admin', 'agent', 'reviewer']

    @field_validator('username','display_name',mode='before')
    @classmethod
    def trim_name(cls,value):
        return value.strip() if isinstance(value,str) else value


class UserUpdate(Model):
    username: str = Field(min_length=2,max_length=100)
    display_name: str = Field(min_length=1,max_length=100)
    role: Literal['admin','agent','reviewer']
    password: str | None = Field(default=None,min_length=12,max_length=200)

    @field_validator('username','display_name',mode='before')
    @classmethod
    def trim_name(cls,value):
        return value.strip() if isinstance(value,str) else value


class ConfirmImport(Model):
    parse_version: int = Field(ge=1)
    accept_warnings: bool = False


class Assignment(Model):
    message_id: UUID
    relation: Literal['question', 'answer', 'progress', 'context', 'correction'] = 'context'


class IssueCreate(Model):
    group_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    messages: list[Assignment] = Field(min_length=1, max_length=1000)


class IssueMessages(Model):
    messages: list[Assignment] = Field(max_length=1000)


class Disposition(Model):
    state: Literal['ignored', 'needs_review']
    reason: str = Field(min_length=1, max_length=2000)


class EvidenceCreate(Model):
    message_id: UUID
    exact_excerpt: str = Field(min_length=1, max_length=20000)
    occurrence: int = Field(default=1, ge=1)


class EvidenceBinding(Model):
    evidence_span_id: UUID
    field_key: str = Field(pattern=r'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_-]*)?$', max_length=160)
    relation: Literal['supports', 'contradicts', 'context'] = 'supports'


class Claim(Model):
    claim_key: str = Field(pattern=r'^[a-z][a-z0-9_-]*$', max_length=80)
    text: str = Field(min_length=1, max_length=20000)


class NextAction(Model):
    text: str = Field(min_length=1, max_length=2000)
    basis: Literal['explicit_in_chat', 'reviewer_suggestion']
    evidence_span_ids: list[UUID] = []


class Contributor(Model):
    participant_id: UUID
    contribution: str = Field(min_length=1, max_length=2000)
    evidence_span_ids: list[UUID] = Field(min_length=1, max_length=100)


class TicketContent(Model):
    title: str = Field(min_length=1, max_length=300)
    first_visible_message_id: UUID
    first_question_message_id: UUID | None = None
    date_basis: Literal['first_question', 'first_visible_context'] = 'first_question'
    problem: str = Field(min_length=1, max_length=20000)
    impact: str = Field(default='', max_length=10000)
    handling_summary: str = Field(default='', max_length=30000)
    current_conclusion: str = Field(default='', max_length=20000)
    claims: list[Claim] = []
    next_actions: list[NextAction] = []
    status: Literal['open','in_progress','waiting_customer','waiting_internal','answered','resolved','cancelled','unknown'] = 'open'


class QAContent(Model):
    question: str = Field(min_length=1, max_length=10000)
    answer: str | None = Field(default=None, max_length=50000)
    answer_state: Literal['supported','no_answer','conflict','missing_context'] = 'supported'
    applicability: str = Field(default='', max_length=5000)
    answer_claims: list[Claim] = []
    contributors: list[Contributor] = []


class RevisionBase(Model):
    expected_object_version: int = Field(ge=1)
    base_revision_id: UUID | None = None
    replaces_revision_id: UUID | None = None
    evidence: list[EvidenceBinding] = Field(default=[], max_length=1000)
    change_reason: str = Field(default='', max_length=2000)


class TicketRevisionCreate(RevisionBase):
    content: TicketContent


class QARevisionCreate(RevisionBase):
    content: QAContent
    issue_ids: list[UUID] = Field(min_length=1, max_length=100)


class QACreate(Model):
    issue_ids: list[UUID] = Field(min_length=1, max_length=100)
    content: QAContent
    evidence: list[EvidenceBinding] = []


class Review(Model):
    expected_object_version: int = Field(ge=1)
    expected_current_revision_id: UUID | None = None
    comment: str = Field(default='', max_length=2000)
    accept_incomplete_start: bool = False


class Note(Model):
    note: str = Field(min_length=1, max_length=4000)


class Extract(Model):
    mode: Literal['ticket','qa','both'] = 'both'
    profile: Literal['local','external'] = 'local'
