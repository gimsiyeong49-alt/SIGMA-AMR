#include "hospital_nav/recovery_manager.hpp"

#include <cmath>

namespace hospital_nav
{

RecoveryManager::RecoveryManager(const RecoveryManagerParams& params)
  : params_(params)
{
}

RecoveryDecision RecoveryManager::decide(const RecoveryContext& ctx) const
{
  RecoveryDecision decision;

  if (!ctx.localization_ok || !ctx.goal_received) {
    decision.action = RecoveryAction::ABORT_TO_IDLE;
    decision.reason_text = "navigation not ready";
    return decision;
  }

  if (ctx.recovery_count >= params_.max_recovery_attempts) {
    decision.action = RecoveryAction::ABORT_TO_IDLE;
    decision.reason_text = "max recovery attempts reached";
    return decision;
  }

  switch (ctx.reason) {
    case FailureReason::OSCILLATION:
      if (ctx.dist_to_goal <= params_.oscillation_ignore_distance) {
        decision.action = RecoveryAction::IGNORE_AND_KEEP_MOVING;
        decision.reason_text = "ignore oscillation near goal";
        return decision;
      }

      if (ctx.dist_to_goal <= params_.near_goal_distance) {
        decision.action = RecoveryAction::REPLAN_ONLY;
        decision.consume_attempt = true;
        decision.reason_text = "oscillation near goal -> replan only";
        return decision;
      }

      if (ctx.recovery_count == 0) {
        decision.action = RecoveryAction::REPLAN_ONLY;
        decision.consume_attempt = true;
        decision.reason_text = "first oscillation -> replan only";
        return decision;
      }

      decision.action = RecoveryAction::SPIN_AND_RETRY;
      decision.consume_attempt = true;
      decision.action_timeout = params_.spin_timeout;
      decision.reason_text = "oscillation -> spin retry";
      return decision;

    case FailureReason::PATH_LOST:
      if (ctx.dist_to_goal <= params_.near_goal_distance) {
        decision.action = RecoveryAction::REPLAN_ONLY;
        decision.consume_attempt = true;
        decision.reason_text = "path lost near goal -> replan only";
        return decision;
      }

      if (ctx.recovery_count == 0) {
        decision.action = RecoveryAction::REPLAN_ONLY;
        decision.consume_attempt = true;
        decision.reason_text = "first path loss -> replan only";
        return decision;
      }

      decision.action = RecoveryAction::BACKUP_AND_RETRY;
      decision.consume_attempt = true;
      decision.action_timeout = params_.backup_timeout;
      decision.reason_text = "path lost -> backup retry";
      return decision;

    case FailureReason::STUCK:
      if (ctx.dist_to_goal <= params_.very_near_goal_distance) {
        decision.action = RecoveryAction::REPLAN_ONLY;
        decision.consume_attempt = true;
        decision.reason_text = "stuck very near goal -> replan only";
        return decision;
      }

      if ((ctx.recovery_count % 2) == 0) {
        decision.action = RecoveryAction::BACKUP_AND_RETRY;
        decision.consume_attempt = true;
        decision.action_timeout = params_.backup_timeout;
        decision.reason_text = "stuck -> backup retry";
      } else {
        decision.action = RecoveryAction::SPIN_AND_RETRY;
        decision.consume_attempt = true;
        decision.action_timeout = params_.spin_timeout;
        decision.reason_text = "stuck -> spin retry";
      }
      return decision;

    case FailureReason::PLANNING_FAILED:
      if (ctx.dist_to_goal <= params_.near_goal_distance) {
        decision.action = RecoveryAction::REPLAN_ONLY;
        decision.consume_attempt = true;
        decision.reason_text = "planning failed near goal -> replan only";
        return decision;
      }

      if ((ctx.recovery_count % 2) == 0) {
        decision.action = RecoveryAction::SPIN_AND_RETRY;
        decision.consume_attempt = true;
        decision.action_timeout = params_.spin_timeout;
        decision.reason_text = "planning failed -> spin retry";
      } else {
        decision.action = RecoveryAction::BACKUP_AND_RETRY;
        decision.consume_attempt = true;
        decision.action_timeout = params_.backup_timeout;
        decision.reason_text = "planning failed -> backup retry";
      }
      return decision;

    case FailureReason::NONE:
    default:
      decision.action = RecoveryAction::NONE;
      decision.reason_text = "no failure";
      return decision;
  }
}

}  // namespace hospital_nav
