import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, DbSession, StaffCompany
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services import api_keys as api_keys_service

# admin territory, session only: a key can never mint or revoke keys
router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(db: DbSession, company: StaffCompany, _admin: AdminUser) -> list[ApiKeyOut]:
    return [ApiKeyOut.model_validate(k) for k in await api_keys_service.list_keys(db, company)]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate, db: DbSession, company: StaffCompany, admin: AdminUser
) -> ApiKeyCreated:
    key, secret = await api_keys_service.create(
        db, company, name=payload.name, scope=payload.scope, actor=admin
    )
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), secret=secret)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID, db: DbSession, company: StaffCompany, admin: AdminUser
) -> None:
    if not await api_keys_service.revoke(db, company, key_id, actor=admin):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
