from typing import Dict, Any, List
import json
import urllib.request
import urllib.parse
import base64
import requests as _requests

from zenpy import Zenpy
from zenpy.lib.api_objects import Comment
from zenpy.lib.api_objects import Ticket as ZenpyTicket


class ZendeskClient:
    def __init__(self, subdomain: str, email: str, token: str):
        """
        Initialize the Zendesk client using zenpy lib and direct API.
        """
        self.client = Zenpy(
            subdomain=subdomain,
            email=email,
            token=token
        )

        # For direct API calls
        self.subdomain = subdomain
        self.email = email
        self.token = token
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        # Create basic auth header
        credentials = f"{email}/token:{token}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode('ascii')
        self.auth_header = f"Basic {encoded_credentials}"

    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """
        Query a ticket by its ID
        """
        try:
            ticket = self.client.tickets(id=ticket_id)
            raw_custom_fields = getattr(ticket, 'custom_fields', None) or []
            custom_fields = [
                {'id': cf.get('id'), 'value': cf.get('value')} if isinstance(cf, dict)
                else {'id': getattr(cf, 'id', None), 'value': getattr(cf, 'value', None)}
                for cf in raw_custom_fields
            ]
            tags = list(getattr(ticket, 'tags', None) or [])
            return {
                'id': ticket.id,
                'subject': ticket.subject,
                'description': ticket.description,
                'status': ticket.status,
                'priority': ticket.priority,
                'created_at': str(ticket.created_at),
                'updated_at': str(ticket.updated_at),
                'requester_id': ticket.requester_id,
                'assignee_id': ticket.assignee_id,
                'organization_id': ticket.organization_id,
                'tags': tags,
                'custom_fields': custom_fields,
            }
        except Exception as e:
            raise Exception(f"Failed to get ticket {ticket_id}: {str(e)}")

    def get_view_tickets(self, view_id: int, limit: int = 25) -> Dict[str, Any]:
        """
        Return tickets in a Zendesk view (filter/queue), plus the view's own
        metadata (title, description, etc.).

        Args:
            view_id: The Zendesk view id (the numeric id in the view URL).
            limit: Max tickets to return. Capped at 100.

        Returns:
            Dict with `view` (view metadata), `count`, `has_more` (whether the
            view contains tickets beyond `limit`), and `tickets` (summary list
            — id, subject, status, priority, timestamps, requester_id,
            assignee_id, tags). `description` is intentionally omitted from the
            per-ticket summary because descriptions can be multi-KB and blow
            the token budget at limit=100; call `get_ticket` for full detail.
        """
        try:
            limit = max(1, min(limit, 100))
            view = self.client.views(id=view_id)
            view_meta = {
                'id': view.id,
                'title': getattr(view, 'title', None),
                'description': getattr(view, 'description', None),
                'active': getattr(view, 'active', None),
                'position': getattr(view, 'position', None),
            }

            ticket_gen = self.client.views.tickets(view=view_id)
            tickets: List[Dict[str, Any]] = []
            has_more = False
            for t in ticket_gen:
                if len(tickets) >= limit:
                    has_more = True
                    break
                tickets.append({
                    'id': t.id,
                    'subject': t.subject,
                    'status': t.status,
                    'priority': t.priority,
                    'created_at': str(t.created_at),
                    'updated_at': str(t.updated_at),
                    'requester_id': t.requester_id,
                    'assignee_id': t.assignee_id,
                    'tags': list(getattr(t, 'tags', None) or []),
                })
            return {
                'view': view_meta,
                'count': len(tickets),
                'has_more': has_more,
                'tickets': tickets,
            }
        except Exception as e:
            raise Exception(f"Failed to get tickets for view {view_id}: {str(e)}")

    def list_views(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Return all views (filters/queues) visible to the API user, with
        their ids and titles. Useful for resolving a view name to an id
        without leaving the agent.

        `active_only=True` calls zenpy's `views.active()` which hits
        `/api/v2/views/active.json`. Passing `active=True` as a kwarg to
        `views()` does NOT filter — it goes through __call__ to the plain
        `/views.json` endpoint and the kwarg is dropped.
        """
        try:
            views_iter = self.client.views.active() if active_only else self.client.views()
            result = []
            for v in views_iter:
                result.append({
                    'id': v.id,
                    'title': getattr(v, 'title', None),
                    'description': getattr(v, 'description', None),
                    'active': getattr(v, 'active', None),
                    'position': getattr(v, 'position', None),
                })
            return result
        except Exception as e:
            raise Exception(f"Failed to list views: {str(e)}")

    def list_ticket_fields(self) -> List[Dict[str, Any]]:
        """
        Return all ticket field definitions in the workspace, including
        custom fields. Used by clients to resolve custom_field ids -> names.
        """
        try:
            fields = self.client.ticket_fields()
            result = []
            for f in fields:
                result.append({
                    'id': f.id,
                    'title': getattr(f, 'title', None),
                    'type': getattr(f, 'type', None),
                    'description': getattr(f, 'description', None),
                    'active': getattr(f, 'active', None),
                    'tag': getattr(f, 'tag', None),
                })
            return result
        except Exception as e:
            raise Exception(f"Failed to list ticket fields: {str(e)}")

    def get_ticket_comments(self, ticket_id: int) -> List[Dict[str, Any]]:
        """
        Get all comments for a specific ticket, including attachment metadata.
        """
        try:
            comments = self.client.tickets.comments(ticket=ticket_id)
            result = []
            for comment in comments:
                attachments = []
                for a in getattr(comment, 'attachments', []) or []:
                    attachments.append({
                        'id': a.id,
                        'file_name': a.file_name,
                        'content_url': a.content_url,
                        'content_type': a.content_type,
                        'size': a.size,
                    })
                result.append({
                    'id': comment.id,
                    'author_id': comment.author_id,
                    'body': comment.body,
                    'html_body': comment.html_body,
                    'public': comment.public,
                    'created_at': str(comment.created_at),
                    'attachments': attachments,
                })
            return result
        except Exception as e:
            raise Exception(f"Failed to get comments for ticket {ticket_id}: {str(e)}")

    # Allowed MIME types. Two groups:
    #   1. Safe images (no SVG — it can carry XML/JS).
    #   2. ZIP-shaped binary bundles. Notability .ntb files are zip archives; logs.zip is zip.
    #      We still enforce ZIP magic bytes on these so the allowlist isn't a blank cheque
    #      for arbitrary binaries — the caller must really be getting a zip.
    _ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
    _ALLOWED_ZIP_TYPES = {
        'application/zip',
        'application/x-zip-compressed',
        'application/octet-stream',  # Zendesk's default for .ntb
        'application/binary',         # observed verbatim on .ntb attachments via Zendesk CDN
    }
    _ALLOWED_TYPES = _ALLOWED_IMAGE_TYPES | _ALLOWED_ZIP_TYPES

    # Magic bytes (file signatures) for each allowed type.
    # ZIP-shaped types share the standard ZIP local-file-header / end-of-central-directory magics.
    _ZIP_MAGIC_BYTES = [
        b'PK\x03\x04',  # local file header — every non-empty zip starts with this
        b'PK\x05\x06',  # end of central directory record for empty zips
        b'PK\x07\x08',  # spanned-archive marker (rare)
    ]
    _MAGIC_BYTES: Dict[str, List[bytes]] = {
        'image/jpeg': [b'\xff\xd8\xff'],
        'image/png':  [b'\x89PNG\r\n\x1a\n'],
        'image/gif':  [b'GIF87a', b'GIF89a'],
        'image/webp': [b'RIFF'],  # RIFF....WEBP — checked further below
        'application/zip':              _ZIP_MAGIC_BYTES,
        'application/x-zip-compressed': _ZIP_MAGIC_BYTES,
        'application/octet-stream':     _ZIP_MAGIC_BYTES,
        'application/binary':           _ZIP_MAGIC_BYTES,
    }

    # 25 MB hard cap. Images stay token-budget-safe; .ntb files (Notability note bundles)
    # routinely run 5-20 MB when they carry imported PDFs.
    _MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

    def get_ticket_attachment(self, content_url: str) -> Dict[str, Any]:
        """
        Fetch an attachment and return base64-encoded data.

        Security measures applied:
        - Allowlist of MIME types: safe images plus ZIP-shaped binary bundles
          (Notability .ntb files are zip archives; logs.zip is zip).
        - Magic byte validation so the file header must match the declared type.
          For ZIP-shaped allowlisted MIME types, we enforce the standard ZIP signature,
          so the binary allowlist is not a blank cheque for arbitrary content.
        - 25 MB size cap to prevent image bombs and excessive token usage.

        Zendesk attachment URLs redirect to zdusercontent.com (Zendesk's CDN).
        requests strips the Authorization header on cross-origin redirects,
        which is required — the CDN returns 403 if it receives an auth header.
        """
        try:
            response = _requests.get(
                content_url,
                headers={'Authorization': self.auth_header},
                timeout=30,
                stream=True,
            )
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()

            if content_type not in self._ALLOWED_TYPES:
                raise ValueError(
                    f"Attachment type '{content_type}' is not allowed. "
                    f"Supported types: {sorted(self._ALLOWED_TYPES)}"
                )

            # Fail fast on declared oversize before buffering anything.
            declared_len_raw = response.headers.get('Content-Length')
            declared_len = None
            if declared_len_raw is not None and declared_len_raw.isdigit():
                declared_len = int(declared_len_raw)
            if declared_len is not None and declared_len > self._MAX_ATTACHMENT_BYTES:
                raise ValueError(
                    f"Attachment exceeds the {self._MAX_ATTACHMENT_BYTES // (1024*1024)} MB size limit."
                )

            # Read with size cap — stops download as soon as limit is exceeded.
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > self._MAX_ATTACHMENT_BYTES:
                    raise ValueError(
                        f"Attachment exceeds the {self._MAX_ATTACHMENT_BYTES // (1024*1024)} MB size limit."
                    )
                chunks.append(chunk)
            content = b''.join(chunks)

            # Validate magic bytes to catch MIME type spoofing.
            magic_signatures = self._MAGIC_BYTES.get(content_type, [])
            if magic_signatures and not any(content.startswith(sig) for sig in magic_signatures):
                raise ValueError(
                    f"File header does not match declared content type '{content_type}'. "
                    "The attachment may be spoofed."
                )
            # Extra check for WebP: bytes 8–12 must be b'WEBP'.
            if content_type == 'image/webp' and content[8:12] != b'WEBP':
                raise ValueError("File header does not match declared content type 'image/webp'.")

            return {
                'data': base64.b64encode(content).decode('ascii'),
                'content_type': content_type,
            }
        except (ValueError, _requests.HTTPError):
            raise
        except Exception as e:
            raise Exception(f"Failed to fetch attachment from {content_url}: {str(e)}")

    def post_comment(self, ticket_id: int, comment: str, public: bool = True) -> str:
        """
        Post a comment to an existing ticket.
        """
        try:
            ticket = self.client.tickets(id=ticket_id)
            ticket.comment = Comment(
                html_body=comment,
                public=public
            )
            self.client.tickets.update(ticket)
            return comment
        except Exception as e:
            raise Exception(f"Failed to post comment on ticket {ticket_id}: {str(e)}")

    def get_tickets(self, page: int = 1, per_page: int = 25, sort_by: str = 'created_at', sort_order: str = 'desc') -> Dict[str, Any]:
        """
        Get the latest tickets with proper pagination support using direct API calls.

        Args:
            page: Page number (1-based)
            per_page: Number of tickets per page (max 100)
            sort_by: Field to sort by (created_at, updated_at, priority, status)
            sort_order: Sort order (asc or desc)

        Returns:
            Dict containing tickets and pagination info
        """
        try:
            # Cap at reasonable limit
            per_page = min(per_page, 100)

            # Build URL with parameters for offset pagination
            params = {
                'page': str(page),
                'per_page': str(per_page),
                'sort_by': sort_by,
                'sort_order': sort_order
            }
            query_string = urllib.parse.urlencode(params)
            url = f"{self.base_url}/tickets.json?{query_string}"

            # Create request with auth header
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')

            # Make the API request
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())

            tickets_data = data.get('tickets', [])

            # Process tickets to return only essential fields
            ticket_list = []
            for ticket in tickets_data:
                ticket_list.append({
                    'id': ticket.get('id'),
                    'subject': ticket.get('subject'),
                    'status': ticket.get('status'),
                    'priority': ticket.get('priority'),
                    'description': ticket.get('description'),
                    'created_at': ticket.get('created_at'),
                    'updated_at': ticket.get('updated_at'),
                    'requester_id': ticket.get('requester_id'),
                    'assignee_id': ticket.get('assignee_id')
                })

            return {
                'tickets': ticket_list,
                'page': page,
                'per_page': per_page,
                'count': len(ticket_list),
                'sort_by': sort_by,
                'sort_order': sort_order,
                'has_more': data.get('next_page') is not None,
                'next_page': page + 1 if data.get('next_page') else None,
                'previous_page': page - 1 if data.get('previous_page') and page > 1 else None
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to get latest tickets: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to get latest tickets: {str(e)}")

    def search(
        self,
        query: str,
        type: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> Dict[str, Any]:
        """
        Full-text search across Zendesk using the Search API
        (/api/v2/search.json). Unlike views, this searches ticket bodies,
        comments, subjects, tags, and more.

        Args:
            query: Zendesk search query string. Supports full-text terms and
                field qualifiers, e.g. 'crash type:ticket status:open'.
                See https://support.zendesk.com/hc/en-us/articles/4408886879258
            type: Optional result type to restrict to (ticket, user,
                organization, group). Prepended as 'type:<type>' if the query
                does not already specify a type.
            sort_by: Optional field to sort by (e.g. created_at, updated_at,
                priority, status, ticket_type).
            sort_order: Optional sort order (asc or desc).
            page: Page number (1-based).
            per_page: Results per page (max 100).

        Returns:
            Dict containing results and pagination info.
        """
        try:
            per_page = min(per_page, 100)

            full_query = query
            if type and f"type:{type}" not in query:
                full_query = f"type:{type} {query}".strip()

            params = {
                'query': full_query,
                'page': str(page),
                'per_page': str(per_page),
            }
            if sort_by:
                params['sort_by'] = sort_by
            if sort_order:
                params['sort_order'] = sort_order

            query_string = urllib.parse.urlencode(params)
            url = f"{self.base_url}/search.json?{query_string}"

            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')

            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())

            return {
                'results': data.get('results', []),
                'count': data.get('count', 0),
                'page': page,
                'per_page': per_page,
                'has_more': data.get('next_page') is not None,
                'next_page': page + 1 if data.get('next_page') else None,
                'previous_page': page - 1 if data.get('previous_page') and page > 1 else None,
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to search: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to search: {str(e)}")

    def get_all_articles(self) -> Dict[str, Any]:
        """
        Fetch help center articles as knowledge base.
        Returns a Dict of section -> [article].
        """
        try:
            # Get all sections
            sections = self.client.help_center.sections()

            # Get articles for each section
            kb = {}
            for section in sections:
                articles = self.client.help_center.sections.articles(section.id)
                kb[section.name] = {
                    'section_id': section.id,
                    'description': section.description,
                    'articles': [{
                        'id': article.id,
                        'title': article.title,
                        'body': article.body,
                        'updated_at': str(article.updated_at),
                        'url': article.html_url
                    } for article in articles]
                }

            return kb
        except Exception as e:
            raise Exception(f"Failed to fetch knowledge base: {str(e)}")

    def create_ticket(
        self,
        subject: str,
        description: str,
        requester_id: int | None = None,
        assignee_id: int | None = None,
        priority: str | None = None,
        type: str | None = None,
        tags: List[str] | None = None,
        custom_fields: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """
        Create a new Zendesk ticket using Zenpy and return essential fields.

        Args:
            subject: Ticket subject
            description: Ticket description (plain text). Will also be used as initial comment.
            requester_id: Optional requester user ID
            assignee_id: Optional assignee user ID
            priority: Optional priority (low, normal, high, urgent)
            type: Optional ticket type (problem, incident, question, task)
            tags: Optional list of tags
            custom_fields: Optional list of dicts: {id: int, value: Any}
        """
        try:
            ticket = ZenpyTicket(
                subject=subject,
                description=description,
                requester_id=requester_id,
                assignee_id=assignee_id,
                priority=priority,
                type=type,
                tags=tags,
                custom_fields=custom_fields,
            )
            created_audit = self.client.tickets.create(ticket)
            # Fetch created ticket id from audit
            created_ticket_id = getattr(getattr(created_audit, 'ticket', None), 'id', None)
            if created_ticket_id is None:
                # Fallback: try to read id from audit events
                created_ticket_id = getattr(created_audit, 'id', None)

            # Fetch full ticket to return consistent data
            created = self.client.tickets(id=created_ticket_id) if created_ticket_id else None

            return {
                'id': getattr(created, 'id', created_ticket_id),
                'subject': getattr(created, 'subject', subject),
                'description': getattr(created, 'description', description),
                'status': getattr(created, 'status', 'new'),
                'priority': getattr(created, 'priority', priority),
                'type': getattr(created, 'type', type),
                'created_at': str(getattr(created, 'created_at', '')),
                'updated_at': str(getattr(created, 'updated_at', '')),
                'requester_id': getattr(created, 'requester_id', requester_id),
                'assignee_id': getattr(created, 'assignee_id', assignee_id),
                'organization_id': getattr(created, 'organization_id', None),
                'tags': list(getattr(created, 'tags', tags or []) or []),
            }
        except Exception as e:
            raise Exception(f"Failed to create ticket: {str(e)}")

    def update_ticket(self, ticket_id: int, **fields: Any) -> Dict[str, Any]:
        """
        Update a Zendesk ticket with provided fields using Zenpy.

        Supported fields include common ticket attributes like:
        subject, status, priority, type, assignee_id, requester_id,
        tags (list[str]), custom_fields (list[dict]), due_at, etc.
        """
        try:
            # Load the ticket, mutate fields directly, and update
            ticket = self.client.tickets(id=ticket_id)
            for key, value in fields.items():
                if value is None:
                    continue
                setattr(ticket, key, value)

            # This call returns a TicketAudit (not a Ticket). Don't read attrs from it.
            self.client.tickets.update(ticket)

            # Fetch the fresh ticket to return consistent data
            refreshed = self.client.tickets(id=ticket_id)

            return {
                'id': refreshed.id,
                'subject': refreshed.subject,
                'description': refreshed.description,
                'status': refreshed.status,
                'priority': refreshed.priority,
                'type': getattr(refreshed, 'type', None),
                'created_at': str(refreshed.created_at),
                'updated_at': str(refreshed.updated_at),
                'requester_id': refreshed.requester_id,
                'assignee_id': refreshed.assignee_id,
                'organization_id': refreshed.organization_id,
                'tags': list(getattr(refreshed, 'tags', []) or []),
            }
        except Exception as e:
            raise Exception(f"Failed to update ticket {ticket_id}: {str(e)}")