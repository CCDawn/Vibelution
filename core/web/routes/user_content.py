from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core.web.routes.user_content_models import (
    MarkdownSpaceImportPayload,
    MarkdownSpaceImportPreviewPayload,
    UserContentMarkdownResponse,
)
from core.web.services import user_content_markdown_service


router = APIRouter(tags=["user-content"])

_NOT_FOUND_CODES = {"space_not_found", "page_not_found"}


def _raise_service_error(error: user_content_markdown_service.UserContentMarkdownError) -> None:
    status_code = status.HTTP_404_NOT_FOUND if error.code in _NOT_FOUND_CODES else status.HTTP_400_BAD_REQUEST
    raise HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": str(error)},
    ) from error


@router.post(
    "/user-content/markdown-spaces/import-preview",
    response_model=UserContentMarkdownResponse,
    response_model_exclude_unset=True,
)
def markdown_space_import_preview(payload: MarkdownSpaceImportPreviewPayload) -> dict:
    try:
        return user_content_markdown_service.preview_markdown_space_import(payload.sourcePath, user_id=payload.userId)
    except user_content_markdown_service.UserContentMarkdownError as error:
        _raise_service_error(error)


@router.post(
    "/user-content/markdown-spaces/import",
    status_code=status.HTTP_201_CREATED,
    response_model=UserContentMarkdownResponse,
    response_model_exclude_unset=True,
)
def markdown_space_import(payload: MarkdownSpaceImportPayload) -> dict:
    try:
        return user_content_markdown_service.import_markdown_space(
            payload.sourcePath,
            user_id=payload.userId,
            space_name=payload.spaceName,
            overwrite=payload.overwrite,
        )
    except user_content_markdown_service.UserContentMarkdownError as error:
        _raise_service_error(error)


@router.get(
    "/user-content/markdown-spaces/search",
    response_model=UserContentMarkdownResponse,
    response_model_exclude_unset=True,
)
def markdown_space_search(
    query: str = "",
    userId: str = "default",
    spaceId: str = "",
    limit: int = 10,
    maxExcerptChars: int = 900,
) -> dict:
    try:
        return user_content_markdown_service.search_user_markdown_spaces(
            user_id=userId,
            query=query,
            space_id=spaceId,
            limit=limit,
            max_excerpt_chars=maxExcerptChars,
        )
    except user_content_markdown_service.UserContentMarkdownError as error:
        _raise_service_error(error)


@router.get(
    "/user-content/markdown-spaces",
    response_model=UserContentMarkdownResponse,
    response_model_exclude_unset=True,
)
def markdown_space_list(userId: str = "default") -> dict:
    return user_content_markdown_service.list_markdown_spaces(user_id=userId)


@router.get(
    "/user-content/markdown-spaces/{space_id}/pages",
    response_model=UserContentMarkdownResponse,
    response_model_exclude_unset=True,
)
def markdown_space_pages(space_id: str, userId: str = "default", query: str = "", tag: str = "") -> dict:
    try:
        return user_content_markdown_service.list_markdown_space_pages(space_id, user_id=userId, query=query, tag=tag)
    except user_content_markdown_service.UserContentMarkdownError as error:
        _raise_service_error(error)


@router.get(
    "/user-content/markdown-spaces/{space_id}/pages/{page_id}",
    response_model=UserContentMarkdownResponse,
    response_model_exclude_unset=True,
)
def markdown_space_page(space_id: str, page_id: str, userId: str = "default") -> dict:
    try:
        payload = user_content_markdown_service.get_markdown_space_page(space_id, page_id, user_id=userId)
    except user_content_markdown_service.UserContentMarkdownError as error:
        _raise_service_error(error)
    return {
        **payload,
        **dict(payload.get("page") or {}),
    }
