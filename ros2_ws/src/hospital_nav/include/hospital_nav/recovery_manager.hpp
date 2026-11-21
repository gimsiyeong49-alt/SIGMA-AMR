#pragma once

#include <string>

namespace hospital_nav
{

enum class FailureReason
{
  NONE,
  PLANNING_FAILED,
  PATH_LOST,
  STUCK,
  OSCILLATION
};

enum class RecoveryAction
{
  NONE,
  IGNORE_AND_KEEP_MOVING,
  REPLAN_ONLY,
  BACKUP_AND_RETRY,
  SPIN_AND_RETRY,
  ABORT_TO_IDLE
};

struct RecoveryManagerParams
{
  int max_recovery_attempts = 2;

  double near_goal_distance = 0.80;
  double very_near_goal_distance = 0.35;
  double oscillation_ignore_distance = 0.80;
  double disable_replan_near_goal_distance = 0.90;

  double backup_timeout = 1.8;
  double spin_timeout = 2.5;
};

struct RecoveryContext
{
  FailureReason reason = FailureReason::NONE;
  double dist_to_goal = 1e9;
  double heading_error = 0.0;
  int recovery_count = 0;
  bool localization_ok = true;
  bool goal_received = true;
};

struct RecoveryDecision
{
  RecoveryAction action = RecoveryAction::NONE;
  bool consume_attempt = false;
  double action_timeout = 0.0;
  std::string reason_text;
};

class RecoveryManager
{
public:
  explicit RecoveryManager(const RecoveryManagerParams& params);

  RecoveryDecision decide(const RecoveryContext& ctx) const;

  const RecoveryManagerParams& params() const { return params_; }

private:
  RecoveryManagerParams params_;
};

}  // namespace hospital_nav
