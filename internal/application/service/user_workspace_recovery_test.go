package service

import (
	"context"
	"errors"
	"testing"

	apprepo "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type recoveryMembers struct {
	interfaces.TenantMemberService
	members []*types.TenantMember
	err     error
}

func (s *recoveryMembers) ListByUser(context.Context, string) ([]*types.TenantMember, error) {
	return s.members, s.err
}

type recoveryTenants struct {
	interfaces.TenantService
	deleted uint64
	err     error
}

func (s *recoveryTenants) GetTenantByID(_ context.Context, id uint64) (*types.Tenant, error) {
	if s.err != nil {
		return nil, s.err
	}
	if id == s.deleted {
		return nil, apprepo.ErrTenantNotFound
	}
	return &types.Tenant{ID: id}, nil
}

func TestHomeTenantRecovery(t *testing.T) {
	active := func(id uint64) *types.TenantMember {
		return &types.TenantMember{TenantID: id, Status: types.TenantMemberStatusActive}
	}
	for _, tt := range []struct {
		name    string
		members []*types.TenantMember
		deleted uint64
		want    uint64
	}{
		{"valid home retained", []*types.TenantMember{active(12), active(42)}, 0, 12},
		{"removed from home selects another", []*types.TenantMember{active(42)}, 0, 42},
		{"removed last membership becomes tenantless", nil, 0, 0},
		{"deleted home selects another", []*types.TenantMember{active(12), active(42)}, 12, 42},
		{"deleted last home becomes tenantless", []*types.TenantMember{active(12)}, 12, 0},
		{"suspended home is not usable", []*types.TenantMember{{TenantID: 12, Status: types.TenantMemberStatusSuspended}, active(42)}, 0, 42},
	} {
		t.Run(tt.name, func(t *testing.T) {
			repo := &stubUserRepoForAuth{}
			svc := &userService{userRepo: repo, memberService: &recoveryMembers{members: tt.members}, tenantService: &recoveryTenants{deleted: tt.deleted}}
			user := &types.User{ID: "member", TenantID: 12}
			if got := svc.resolveLoginTenantID(context.Background(), user); got != tt.want {
				t.Fatalf("tenant=%d want %d", got, tt.want)
			}
			if user.TenantID != tt.want {
				t.Fatalf("stale home retained: %d", user.TenantID)
			}
			if tt.want != 12 && repo.updateCalls != 1 {
				t.Fatalf("repair writes=%d want 1", repo.updateCalls)
			}
		})
	}
}

func TestHomeTenantRecoveryDoesNotEraseHomeOnOutage(t *testing.T) {
	for _, membershipFailure := range []bool{true, false} {
		members := &recoveryMembers{members: []*types.TenantMember{{TenantID: 12, Status: types.TenantMemberStatusActive}}}
		tenants := &recoveryTenants{}
		if membershipFailure {
			members.err = errors.New("database unavailable")
		} else {
			tenants.err = errors.New("database unavailable")
		}
		repo := &stubUserRepoForAuth{}
		svc := &userService{userRepo: repo, memberService: members, tenantService: tenants}
		user := &types.User{ID: "member", TenantID: 12}
		if got := svc.resolveLoginTenantID(context.Background(), user); got != 12 || repo.updateCalls != 0 {
			t.Fatalf("outage changed home: %d writes=%d", got, repo.updateCalls)
		}
	}
}
