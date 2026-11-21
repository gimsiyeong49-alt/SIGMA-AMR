#pragma once

#include <boost/lexical_cast.hpp>
#include <boost/algorithm/string/split.hpp>
#include <boost/algorithm/string/trim.hpp>
#include <boost/algorithm/string/replace.hpp>
#include <boost/algorithm/string/classification.hpp>


#include <iostream>
#include <sstream>
#include <typeinfo>
#include <cassert>
#include <mutex>
#include <math.h>
#include <chrono>
#include <memory>
#include <vector>
#include <map>

#include <serial/serial.h>
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"
#include "std_msgs/msg/empty.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "nav_msgs/msg/odometry.hpp"

#include "roboteq_interfaces/msg/channel_values.hpp"

// #include "roboteq_controller/msg/config.hpp"
// #include "roboteq_controller/msg/maintenance.hpp"

// #include "roboteq_controller/querylist.h"
// #include "roboteq_controller/channel_values.h"


using namespace std::chrono_literals;
using std::placeholders::_1;

class RoboteqDriver : public rclcpp::Node
{
public:
	explicit RoboteqDriver(const rclcpp::NodeOptions &options = rclcpp::NodeOptions());

	~RoboteqDriver(){
		if (ser_.isOpen()){
			ser_.close();
		}
	}

private:
	
	// Serial
	serial::Serial 			ser_;
	std::string 			serial_port_;
	int32_t 				baudrate_;

	// Pub & Sub
	rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr 		cmd_vel_sub_;
	rclcpp::Publisher<std_msgs::msg::String>::SharedPtr 		serial_read_pub_;
	
	std::vector<rclcpp::Publisher<roboteq_interfaces::msg::ChannelValues>::SharedPtr>  query_pub_;

	rclcpp::TimerBase::SharedPtr 				timer_pub_;

	bool 					closed_loop_,
							diff_drive_mode_;

	double 					wheel_circumference_,
							track_width_,
							max_rpm_;

	std::string 			cmd_vel_topic_;

	// queries
	std::map<std::string, std::string>	queries_;

	// int channel_number_1;
	// int channel_number_2;
	int frequency_;
	std::mutex 				locker;

	void declare();
	void init();

	// 2026-11-13: 속도 완만화(가감속 제한) — 목표 도착 때 Nav2 가 속도 0 을 한 번에 보내 급정지(실측 0.98 m/s²)하던 문제.
	//  모든 /cmd_vel(Nav2·복귀 정렬·복구 동작)을 여기서 목표값으로만 받고, 타이머가 가감속 한도 안에서 실제 명령을 올리고 내린다.
	//  명령이 cmd_timeout 초 넘게 안 오면 목표를 0 으로(완만하게 정지) — 예전엔 마지막 명령을 계속 유지했음.
	bool 					smooth_enable_ = true;
	double 					max_lin_acc_ = 0.25, max_lin_dec_ = 0.3, max_ang_acc_ = 0.6, max_ang_dec_ = 0.8;
	double 					cmd_timeout_ = 0.5, smooth_rate_ = 20.0;
	double 					cur_v_ = 0.0, cur_w_ = 0.0, tgt_v_ = 0.0, tgt_w_ = 0.0;
	bool 					sent_zero_ = true;
	rclcpp::Time 			last_cmd_time_;
	rclcpp::TimerBase::SharedPtr 				smooth_timer_;
	void smoothStep();
	void sendWheelCommand(double v, double w);

	// 2026-11-15: 조이스틱 전용 입력(joy_cmd_topic, 기본 /cmd_vel_joy). /cmd_vel 완만화(감속 0.3)가 조이스틱에도 걸려
	//  L1 을 놓아도 한참 밀려가던 문제(벽에 박을 뻔함) 대응. 조이스틱은 빠른 한도(감속 1.0 m/s²)로 따라가고,
	//  조이스틱이 명령하는 동안(+놓은 뒤 멈출 때까지)은 /cmd_vel(Nav2·복귀 정렬)보다 우선. 신호 끊기면 빠르게 정지.
	std::string 			joy_cmd_topic_ = "/cmd_vel_joy";
	double 					joy_lin_acc_ = 0.5, joy_lin_dec_ = 1.0, joy_ang_acc_ = 1.5, joy_ang_dec_ = 2.0, joy_timeout_ = 0.5;
	double 					max_lin_vel_ = 0.5, max_ang_vel_ = 1.0;     // 모든 입력 공통 안전 상한(실제 속도, 0 이하=제한 없음)
	double 					joy_v_ = 0.0, joy_w_ = 0.0;
	bool 					joy_active_ = false;
	rclcpp::Time 			last_joy_time_;
	rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr 		joy_sub_;
	void joyCmdCallback(const geometry_msgs::msg::Twist &);
	void dumpConfig();     // 2026-11-15: 속도 제어 설정 읽기만(~ 명령) → 로그
	bool speed_pid_enable_ = false;
	double speed_kp_ = 0.0, speed_ki_ = 1.0, speed_kd_ = 0.0;   // 컨트롤러 속도 PID(실제 게인, 보낼 땐 ×10^6)

	void cmdSetup();
	void cmdVelCallback(const geometry_msgs::msg::Twist &);
	void powerCmdCallback(const geometry_msgs::msg::Twist &);
	// bool configService(roboteq_interfaces::config_srv::Request &, roboteq_interfaces::config_srv::Response &);
	// bool commandService(roboteq_interfaces::command_srv::Request &, roboteq_interfaces::command_srv::Response &);
	// bool maintenanceService(roboteq_interfaces::maintenance_srv::Request &, roboteq_interfaces::maintenance_srv::Response &);
	void initializeServices();
	void run();

	void queryCallback();

};