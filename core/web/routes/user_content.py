from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services import user_content_markdown_service


router = APIRouter(tags=["user-content"])

_NOT_FOUND_CODES = {"space_not_found", "page_not_found"}


class MarkdownSpaceImportPreviewPayload(BaseModel):
    sourcePath: str = Field(..., min_length=1, max_length=2000)
    userId: str = Field("default", max_length=160)


class MarkdownSpaceImportPayload(MarkdownSpaceImportPreviewPayload):
    spaceName: str = Field("", max_length=180)
    overwrite: bool = False


def _raise_service_error(exc: user_content_markdown_service.UserContentMarkdownError) -> None:
    status_code = status.HTTP_404_NOT_FOUND if exc.code in _NOT_FOUND_CODES else status.HTTP_400_BAD_REQUEST
    raise HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


@router.post("/user-content/markdown-spaces/import-preview")
def markdown_space_import_preview(payload: MarkdownSpaceImportPreviewPayload) -> dict[str, Any]:
    try:
        return user_content_markdown_service.preview_markdown_space_import(payload.sourcePath, user_id=payload.userId)
    except user_content_markdown_service.UserContentMarkdownError as exc:
        _raise_service_error(exc)


@router.post("/user-content/markdown-spaces/import", status_code=status.HTTP_201_CREATED)
def markdown_space_import(payload: MarkdownSpaceImportPayload) -> dict[str, Any]:
    try:
        return user_content_markdown_service.import_markdown_space(
            payload.sourcePath,
            user_id=payload.userId,
            space_name=payload.spaceName,
            overwrite=payload.overwrite,
        )
    except user_content_markdown_service.UserContentMarkdownError as exc:
        _raise_service_error(exc)


@router.get("/user-content/markdown-spaces/search")
def markdown_space_search(
    query: str = "",
    userId: str = "default",
    spaceId: str = "",
    limit: int = 10,
    maxExcerptChars: int = 900,
) -> dict[str, Any]:
    try:
        return user_content_markdown_service.search_user_markdown_spaces(
            user_id=userId,
            query=query,
            space_id=spaceId,
            limit=limit,
            max_excerpt_chars=maxExcerptChars,
        )
    except user_content_markdown_service.UserContentMarkdownError as exc:
        _raise_service_error(exc)


@router.get("/user-content/markdown-spaces")
def markdown_space_list(userId: str = "default") -> dict[str, Any]:
    return user_content_markdown_service.list_markdown_spaces(user_id=userId)


@router.get("/user-content/markdown-spaces/{space_id}/pages")
def markdown_space_pages(space_id: str, userId: str = "default", query: str = "", tag: str = "") -> dict[str, Any]:
    try:
        return user_content_markdown_service.list_markdown_space_pages(space_id, user_id=userId, query=query, tag=tag)
    except user_content_markdown_service.UserContentMarkdownError as exc:
        _raise_service_error(exc)


@router.get("/user-content/markdown-spaces/{space_id}/pages/{page_id}")
def markdown_space_page(space_id: str, page_id: str, userId: str = "default") -> dict[str, Any]:
    try:
        payload = user_content_markdown_service.get_markdown_space_page(space_id, page_id, user_id=userId)
    except user_content_markdown_service.UserContentMarkdownError as exc:
        _raise_service_error(exc)
    return {
        **payload,
        **dict(payload.get("page") or {}),
    }
