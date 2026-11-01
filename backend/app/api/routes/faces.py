"""Face enrollment and gallery endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import (
    CompoundScope,
    CurrentUser,
    ManagerUser,
    PaginationDep,
    SessionDep,
)
from app.core.exceptions import PermissionDeniedError
from app.schemas.common import Message, Page
from app.schemas.security import FaceEmbeddingRead, FaceGalleryInfo
from app.services.face_service import face_service
from app.services.permissions import enforce_compound, is_manager
from app.services.resident_service import resident_service

router = APIRouter(prefix="/faces", tags=["Face Recognition"])


@router.get("", response_model=Page[FaceEmbeddingRead], summary="List face embeddings")
async def list_faces(
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    resident_id: uuid.UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> Page[FaceEmbeddingRead]:
    if is_manager(user):
        scope = compound_id
    else:
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None:
            raise PermissionDeniedError("No resident profile is linked to this account")
        scope = profile.compound_id
        resident_id = profile.id
    page = await face_service.list(
        session,
        pagination.to_params(),
        compound_id=scope,
        resident_id=resident_id,
        is_active=is_active,
        search=search,
    )
    return Page[FaceEmbeddingRead].create(
        [FaceEmbeddingRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.get("/gallery", response_model=FaceGalleryInfo, summary="Face gallery statistics")
async def gallery_info(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> FaceGalleryInfo:
    return await face_service.gallery_info(session, compound_id)


@router.post(
    "/enroll",
    response_model=FaceEmbeddingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a face for a resident",
)
async def enroll_face(
    session: SessionDep,
    user: CurrentUser,
    file: UploadFile = File(..., description="Clear frontal photo (JPEG/PNG)"),
    resident_id: uuid.UUID = Form(..., description="Resident to enroll"),
    overwrite: bool = Form(default=False),
) -> FaceEmbeddingRead:
    resident = await resident_service.get(session, resident_id)
    if is_manager(user):
        enforce_compound(user, resident.compound_id)
    else:
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None or profile.id != resident_id:
            raise PermissionDeniedError("You can only enroll your own face")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise PermissionDeniedError("Only image uploads are supported")
    data = await file.read()
    embedding, similarity = await face_service.enroll(
        session,
        compound_id=resident.compound_id,
        resident_id=resident_id,
        image_data=data,
        actor_id=user.id,
        overwrite=overwrite,
    )
    result = FaceEmbeddingRead.model_validate(embedding)
    result.similarity_to_existing = similarity
    return result


@router.delete("/{embedding_id}", response_model=Message, summary="Delete a face embedding")
async def delete_face(
    embedding_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    embedding = await face_service.get(session, embedding_id)
    if is_manager(user):
        enforce_compound(user, embedding.compound_id)
    else:
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None or embedding.resident_id != profile.id:
            raise PermissionDeniedError("You can only delete your own face data")
    await face_service.delete(session, embedding_id)
    return Message(message="Face embedding deleted")


@router.post(
    "/{embedding_id}/deactivate",
    response_model=FaceEmbeddingRead,
    summary="Deactivate a face embedding",
)
async def deactivate_face(
    embedding_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> FaceEmbeddingRead:
    embedding = await face_service.get(session, embedding_id)
    enforce_compound(manager, embedding.compound_id)
    return FaceEmbeddingRead.model_validate(
        await face_service.deactivate(session, embedding_id)
    )
