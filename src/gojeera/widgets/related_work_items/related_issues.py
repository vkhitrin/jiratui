from typing import cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widget import Widget
from textual.widgets import Collapsible, Link, LoadingIndicator, Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.models import JiraIssue, RelatedJiraIssue
from gojeera.utils.urls import build_external_url_for_issue
from gojeera.widgets.confirmation_screen import ConfirmationScreen
from gojeera.widgets.constants import RELATED_WORK_ITEMS_PRIORITY_BASED_STYLING
from gojeera.widgets.related_work_items.add import AddWorkItemRelationshipScreen
from gojeera.widgets.work_item_details.read_only_details import WorkItemReadOnlyDetailsScreen


class RelatedIssuesContainer(Container):
    """The container that holds the related issues."""

    def __init__(self):
        super().__init__(id='related-issues-container')
        # Container is always visible - only children are dynamically added/removed


class RelatedIssueCollapsible(Collapsible):
    """A collapsible to show a work item related to another item."""

    BINDINGS = [
        Binding(
            key='v',
            action='view_work_item',
            description='View Work Item',
            show=True,
            key_display='v',
        ),
        Binding(
            key='d',
            action='unlink_work_item',
            description='Unlink Work Item',
            key_display='d',
        ),
    ]
    NOTIFICATIONS_DEFAULT_TITLE = 'Related Work Items'

    def __init__(self, *args, **kwargs):
        self._work_item_key: str | None = kwargs.pop('work_item_key', None)
        self._link_id: str | None = kwargs.pop('link_id', None)
        super().__init__(*args, **kwargs)

    @property
    def work_item_key(self) -> str | None:
        return self._work_item_key

    async def action_view_work_item(self) -> None:
        if self.work_item_key:
            await self.app.push_screen(WorkItemReadOnlyDetailsScreen(self.work_item_key))

    async def action_unlink_work_item(self) -> None:
        await self.app.push_screen(
            ConfirmationScreen('Are you sure you want to delete the link between the issues?'),
            callback=self.handle_delete_choice,
        )

    def handle_delete_choice(self, result: bool | None) -> None:
        if result is True:
            self.run_worker(self.delete_link())

    async def delete_link(self) -> None:
        """Removes a link between two work items.

        After removing a link the list of links is updated by removing the item from the list without fetching data
        from the API.

        Returns:
            Nothing
        """

        application = cast('JiraApp', self.app)  # type:ignore[name-defined] # noqa: F821
        response: APIControllerResponse = await application.api.delete_issue_link(self._link_id)
        if not response.success:
            self.notify(
                f'Failed to delete the link: {response.error}',
                severity='error',
                title=self.NOTIFICATIONS_DEFAULT_TITLE,
            )
        else:
            self.notify(
                'Link between work items deleted successfully',
                title=self.NOTIFICATIONS_DEFAULT_TITLE,
            )
            self.parent.issues = [i for i in self.parent.issues or [] if i.id != self._link_id]  # type:ignore[attr-defined]


class RelatedIssuesWidget(VerticalScroll):
    """A container for displaying the work items related to a work item."""

    HELP = 'See Related Work Items section in the help'
    BINDINGS = [
        Binding(
            key='n',
            action='link_work_item',
            description='New Related',
            key_display='n',
        )
    ]

    issues: Reactive[list[RelatedJiraIssue] | None] = reactive(None)
    NOTIFICATIONS_DEFAULT_TITLE = 'Related Work Items'

    def __init__(self):
        super().__init__(id='related_issues')
        self._issue_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#related-work-items'

    @property
    def issue_key(self) -> str | None:
        return self._issue_key

    @issue_key.setter
    def issue_key(self, value: str | None) -> None:
        self._issue_key = value

    @property
    def loading_container(self) -> Center:
        return self.query_one('.tab-loading-container', expect_type=Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', expect_type=VerticalGroup)

    @property
    def related_issues_container_widget(self) -> RelatedIssuesContainer:
        return self.query_one(RelatedIssuesContainer)

    def compose(self) -> ComposeResult:
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True  # Ensure content container starts visible
            with RelatedIssuesContainer():
                pass

    def show_loading(self) -> None:
        """Show the loading indicator and hide content."""
        self.loading_container.display = True
        self.content_container.display = False

    def hide_loading(self) -> None:
        """Hide the loading indicator and show content."""
        self.loading_container.display = False
        self.content_container.display = True

    def add_relationship(self, data: dict | None = None) -> None:
        if data:
            self.run_worker(self.link_work_items(data))

    async def action_link_work_item(self) -> None:
        """Opens a screen to adda link between two work items."""

        if self.issue_key:
            await self.app.push_screen(
                AddWorkItemRelationshipScreen(self.issue_key), callback=self.add_relationship
            )
        else:
            self.notify(
                'Select a work item before attempting to add a link.',
                title=self.NOTIFICATIONS_DEFAULT_TITLE,
            )

    async def link_work_items(self, data: dict) -> None:
        application = cast('JiraApp', self.app)  # type:ignore[name-defined] # noqa: F821
        response: APIControllerResponse = await application.api.link_work_items(
            left_issue_key=self.issue_key,
            right_issue_key=data.get('right_issue_key'),
            link_type=data.get('link_type'),
            link_type_id=data.get('link_type_id'),
        )
        if not response.success:
            self.notify(
                f'Failed to link the work items: {response.error}',
                severity='error',
                title=self.NOTIFICATIONS_DEFAULT_TITLE,
            )
        else:
            self.notify('Work items linked successfully', title=self.NOTIFICATIONS_DEFAULT_TITLE)
            # fetch the issue but only the issue-links field
            response = await application.api.get_issue(self.issue_key, fields=['issuelinks'])
            if response.success and response.result and response.result.issues:
                work_item: JiraIssue = response.result.issues[0]
                self.issues = work_item.related_issues or []

    def watch_issues(self, items: list[RelatedJiraIssue] | None) -> None:
        """Updates the list of work items related to the currently-selected item.

        Args:
            items: the list of items related to the current work item.

        Returns:
            None
        """
        # Get the related issues container where issues will be mounted
        related_issues_container = self.related_issues_container_widget

        # Always clear existing children first
        related_issues_container.remove_children()

        # If no items, make sure content is visible (not loading) and leave container empty
        if not items:
            self.loading_container.display = False
            self.content_container.display = True
            return

        rows: list[RelatedIssueCollapsible] = []
        issue: RelatedJiraIssue
        for issue in items:
            children: list[Widget] = [Static(Text(issue.cleaned_summary()))]

            if browsable_url := build_external_url_for_issue(issue.key):
                children.append(
                    Link(
                        browsable_url, url=browsable_url, tooltip='open link in the default browser'
                    )
                )

            collapsible = RelatedIssueCollapsible(
                *children,
                title=Text(f'{issue.link_type} | {issue.key} | {issue.display_status()}'),
                work_item_key=issue.key,
                link_id=issue.id,
            )
            if issue.priority_name:
                collapsible.border_subtitle = f'{issue.priority_name} priority'
            styles: dict | None = RELATED_WORK_ITEMS_PRIORITY_BASED_STYLING.get(
                issue.priority_name.lower(), {}
            )
            if styles and (collapsible_class := styles.get('collapsible_class')):
                collapsible.add_class(collapsible_class)
            rows.append(collapsible)

        # Mount the related issues inside the RelatedIssuesContainer
        related_issues_container.mount_all(rows)
