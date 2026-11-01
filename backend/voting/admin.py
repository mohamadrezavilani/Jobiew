from django.contrib import admin
from .models import ActiveVote,VoteRevision,IdentityVerification

@admin.register(IdentityVerification)
class IdentityVerificationAdmin(admin.ModelAdmin):
    list_display=('user','status','provider','checked_at')
    # Deliberately read-only until real Shahkar verification exists.
    readonly_fields=('user','status','provider','checked_at')
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False

@admin.register(VoteRevision)
class VoteRevisionAdmin(admin.ModelAdmin):
    list_display=('user','company','issued_at')
    readonly_fields=('user','company','scores','issued_at','idempotency_key')
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(ActiveVote)
class ActiveVoteAdmin(admin.ModelAdmin):
    list_display=('user','revision')
    readonly_fields=('user','revision')
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False
