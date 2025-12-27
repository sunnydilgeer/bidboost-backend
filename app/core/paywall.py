from dataclasses import dataclass
from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.auth import User, get_current_active_user
from app.core.entitlements import get_entitlements, UPGRADE_MESSAGES

@dataclass
class UpgradeRequired(Exception):
    feature: str
    message: str

def require_entitlement(feature: str):
    def dep(
        current_user: User = Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ):
        ent = get_entitlements(db, current_user.firm_id)
        if not ent.get(feature, False):
            raise UpgradeRequired(
                feature=feature,
                message=UPGRADE_MESSAGES.get(feature, "Upgrade to Pro to unlock this feature.")
            )
        return True
    return dep