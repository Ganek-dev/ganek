"""Dashboard v2 feeds (screen 06): activity log + manual tasks queue."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentCompany, CurrentUser, DbSession
from app.models import Task
from app.schemas.dashboard import ActivityOut, TaskCreate, TaskOut, TaskUpdate
from app.services import activity as activity_service

router = APIRouter(tags=["dashboard"])


@router.get("/activity", response_model=list[ActivityOut])
async def list_activity(
    db: DbSession, company: CurrentCompany, limit: int = 15
) -> list[ActivityOut]:
    return [
        ActivityOut.model_validate(row)
        for row in await activity_service.list_recent(db, company, limit=max(1, min(limit, 50)))
    ]


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    db: DbSession, company: CurrentCompany, include_done: bool = False
) -> list[Task]:
    query = select(Task).where(Task.company_id == company.id).order_by(Task.created_at)
    if not include_done:
        query = query.where(Task.done_at.is_(None))
    return list((await db.execute(query)).scalars().all())


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate, db: DbSession, company: CurrentCompany, user: CurrentUser
) -> Task:
    task = Task(
        company_id=company.id,
        created_by=user.id,
        assignee_user_id=payload.assignee_user_id,
        title=payload.title,
        note=payload.note,
        due_date=payload.due_date,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _task_or_404(db: DbSession, company: CurrentCompany, task_id: uuid.UUID) -> Task:
    task = (
        await db.execute(select(Task).where(Task.company_id == company.id, Task.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID, payload: TaskUpdate, db: DbSession, company: CurrentCompany
) -> Task:
    task = await _task_or_404(db, company, task_id)
    if payload.title is not None:
        task.title = payload.title
    if payload.note is not None:
        task.note = payload.note
    if payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.done is not None:
        task.done_at = datetime.now(UTC) if payload.done else None
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, db: DbSession, company: CurrentCompany) -> None:
    task = await _task_or_404(db, company, task_id)
    await db.delete(task)
    await db.commit()
