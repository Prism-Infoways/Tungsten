"""Actions: buttons, confirmation boxes and modal forms."""

from .action import Action, ActionGroup, BulkAction, BulkActionGroup, Halt, flatten_actions
from .prebuilt import (
    AssociateAction,
    AttachAction,
    CreateAction,
    DeleteAction,
    DeleteBulkAction,
    DetachAction,
    DetachBulkAction,
    DissociateAction,
    DissociateBulkAction,
    EditAction,
    ForceDeleteAction,
    ForceDeleteBulkAction,
    ReplicateAction,
    RestoreAction,
    RestoreBulkAction,
    ViewAction,
)

__all__ = [
    "Action", "ActionGroup", "AssociateAction", "AttachAction", "BulkAction", "BulkActionGroup", "CreateAction", "DeleteAction",
    "DeleteBulkAction", "DetachAction", "DetachBulkAction", "DissociateAction",
    "DissociateBulkAction", "EditAction", "ForceDeleteAction",
    "ForceDeleteBulkAction", "Halt", "ReplicateAction", "RestoreAction", "RestoreBulkAction", "ViewAction",
    "flatten_actions",
]
