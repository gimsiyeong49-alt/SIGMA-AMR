#include <cmath>
#include <thread>
#include <chrono>
#include <algorithm>
#include "roboteq_controller/roboteq_controller_node.h"

// static const std::string tag {"[RoboteQ] "};
static const std::string tag {""};

void RoboteqDriver::declare(){
	declare_parameter<std::string>("serial_port", "dev/ttyUSB0");
	declare_parameter("baudrate", 112500);
	declare_parameter("closed_loop", false);
	declare_parameter("diff_drive_mode", false);
	declare_parameter("wheel_circumference", 0.0);
	declare_parameter("track_width", 0.0);
	declare_parameter("max_rpm", 0.0);
	declare_parameter<int>("frequency", 0);
	declare_parameter<std::string>("cmd_vel_topic", "cmd_vel");
	declare_parameter("smooth_enable", true);
	declare_parameter("max_lin_acc", 0.25);
	declare_parameter("max_lin_dec", 0.3);
	declare_parameter("max_ang_acc", 0.6);
	declare_parameter("max_ang_dec", 0.8);
	declare_parameter("cmd_timeout", 0.5);
	declare_parameter("smooth_rate", 20.0);
	declare_parameter<std::string>("joy_cmd_topic", "/cmd_vel_joy");
	declare_parameter("joy_lin_acc", 0.5);
	declare_parameter("joy_lin_dec", 1.0);
	declare_parameter("joy_ang_acc", 1.5);
	declare_parameter("joy_ang_dec", 2.0);
	declare_parameter("joy_timeout", 0.5);
	declare_parameter("max_lin_vel", 0.5);
	declare_parameter("max_ang_vel", 1.0);
	declare_parameter("speed_pid_enable", false);
	declare_parameter("speed_kp", 0.0);
	declare_parameter("speed_ki", 1.0);
	declare_parameter("speed_kd", 0.0);
}

void RoboteqDriver::init(){
	RCLCPP_INFO(get_logger(), "Creating");
	get_parameter("frequency", frequency_);

	get_parameter("serial_port", serial_port_);
	get_parameter("baudrate", baudrate_);

	get_parameter("closed_loop", closed_loop_);
	get_parameter("diff_drive_mode", diff_drive_mode_);
	
	get_parameter("wheel_circumference", wheel_circumference_);
	get_parameter("track_width", track_width_);
	get_parameter("max_rpm", max_rpm_);
	get_parameter("cmd_vel_topic", cmd_vel_topic_);
	get_parameter("smooth_enable", smooth_enable_);
	get_parameter("max_lin_acc", max_lin_acc_);
	get_parameter("max_lin_dec", max_lin_dec_);
	get_parameter("max_ang_acc", max_ang_acc_);
	get_parameter("max_ang_dec", max_ang_dec_);
	get_parameter("cmd_timeout", cmd_timeout_);
	get_parameter("smooth_rate", smooth_rate_);
	get_parameter("joy_cmd_topic", joy_cmd_topic_);
	get_parameter("joy_lin_acc", joy_lin_acc_);
	get_parameter("joy_lin_dec", joy_lin_dec_);
	get_parameter("joy_ang_acc", joy_ang_acc_);
	get_parameter("joy_ang_dec", joy_ang_dec_);
	get_parameter("joy_timeout", joy_timeout_);
	get_parameter("max_lin_vel", max_lin_vel_);
	get_parameter("max_ang_vel", max_ang_vel_);
	get_parameter("speed_pid_enable", speed_pid_enable_);
	get_parameter("speed_kp", speed_kp_);
	get_parameter("speed_ki", speed_ki_);
	get_parameter("speed_kd", speed_kd_);

	RCLCPP_INFO_STREAM(this->get_logger(),tag << "cmd_vel:" << cmd_vel_topic_);

	if (closed_loop_){
		RCLCPP_INFO_STREAM(this->get_logger(),tag << "In CLOSED-LOOP mode!!!! serial port:" << serial_port_);
	}
	else{
		RCLCPP_INFO_STREAM(this->get_logger(),tag << "In OPEN-LOOP mode!!!!");
	}

	if (wheel_circumference_ <=0.0 ){
		RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Inproper configuration! wheel_circumference need to be greater than zero.");
	}
	if (track_width_ <=0.0 ){
		RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Inproper configuration! track_width need to be greater than zero.");
	}
	if ( max_rpm_ <=0.0 ){
		RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Inproper configuration! max_rpm need to be greater than zero.");
	}

	if (frequency_ <= 0.0){
		RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Inproper configuration! \'frequency\' need to be greater than zero.");
	}

	auto param_interface = this->get_node_parameters_interface();
	std::map<std::string, rclcpp::ParameterValue> params = param_interface->get_parameter_overrides();

	RCLCPP_INFO_STREAM(this->get_logger(), tag << "queries:" );

	for (auto iter = params.begin(); iter != params.end(); iter++){
		std::size_t pos = iter->first.find("query");
		if (pos != std::string::npos && 
			iter->second.get_type() == rclcpp::ParameterType::PARAMETER_STRING){
  			std::string topic = iter->first.substr (pos+ 6);    
			auto query = iter->second.to_value_msg().string_value;
			
			queries_[topic] =  query;
			RCLCPP_INFO(this->get_logger(), "%15s : %s",  topic.c_str(), query.c_str() );
		}
	}
}


RoboteqDriver::RoboteqDriver(const rclcpp::NodeOptions &options): Node("roboteq_controller", options),
	wheel_circumference_(0.),
	track_width_(0.),
	max_rpm_(0.),
	frequency_(0),
	serial_port_("dev/ttyUSB0"),
	baudrate_(112500),
	closed_loop_(false),
	diff_drive_mode_(false),
	cmd_vel_topic_("cmd_vel"){
	
	declare();
	init();

	if (diff_drive_mode_){
		cmd_vel_sub_ = create_subscription<geometry_msgs::msg::Twist>(
										cmd_vel_topic_, rclcpp::SystemDefaultsQoS(),
										std::bind(&RoboteqDriver::cmdVelCallback, this, std::placeholders::_1));
		if (!joy_cmd_topic_.empty()){
			joy_sub_ = create_subscription<geometry_msgs::msg::Twist>(
										joy_cmd_topic_, rclcpp::SystemDefaultsQoS(),
										std::bind(&RoboteqDriver::joyCmdCallback, this, std::placeholders::_1));
		}
	}
	else{
		cmd_vel_sub_ = create_subscription<geometry_msgs::msg::Twist>(
										cmd_vel_topic_, rclcpp::SystemDefaultsQoS(),
										std::bind(&RoboteqDriver::powerCmdCallback, this, std::placeholders::_1));
	}

	try{
		ser_.setPort(serial_port_);
		ser_.setBaudrate(baudrate_);
		serial::Timeout timeout = serial::Timeout::simpleTimeout(1000);
		ser_.setTimeout(timeout);
		ser_.open();
	}
	catch (serial::IOException &e){
		RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Unable to open port " << serial_port_);
		rclcpp::shutdown();
	}

	if (ser_.isOpen()){
		RCLCPP_INFO_STREAM(this->get_logger(),tag << "Serial Port " << serial_port_ << " initialized");
	}
	else{
		RCLCPP_INFO_STREAM(this->get_logger(),tag << "Serial Port " << serial_port_ << " is not open");
		rclcpp::shutdown();
	}

	cmdSetup();
	dumpConfig();

	last_cmd_time_ = this->now();
	last_joy_time_ = this->now();
	if (diff_drive_mode_){
		RCLCPP_INFO(this->get_logger(), "[ROBOTEQ] 조이스틱 입력 %s: 감속 %.2f m/s²·회전 감속 %.2f rad/s², 신호 끊김 %.1fs 면 정지, "
		            "/cmd_vel 보다 우선 · 안전 상한 직진 %.2f m/s·회전 %.2f rad/s", joy_cmd_topic_.c_str(),
		            joy_lin_dec_, joy_ang_dec_, joy_timeout_, max_lin_vel_, max_ang_vel_);
	}
	if (diff_drive_mode_ && smooth_enable_){
		RCLCPP_INFO(this->get_logger(), "[ROBOTEQ] 속도 완만화 켬: 직진 가속 %.2f/감속 %.2f m/s², 회전 가속 %.2f/감속 %.2f rad/s², "
		            "명령 끊김 %.1fs 면 정지, %.0fHz", max_lin_acc_, max_lin_dec_, max_ang_acc_, max_ang_dec_, cmd_timeout_, smooth_rate_);
		smooth_timer_ = this->create_wall_timer(
			std::chrono::microseconds(static_cast<int64_t>(1e6 / std::max(1.0, smooth_rate_))),
			std::bind(&RoboteqDriver::smoothStep, this));
	}

	run();
}


void RoboteqDriver::cmdSetup(){
	ser_.write("!G 1 0\r");
	ser_.write("!G 2 0\r");
	ser_.write("!S 1 0\r");
	ser_.write("!S 2 0\r");
	ser_.flush();

	ser_.write("^RWD 1000\r");

	if (!closed_loop_){
		ser_.write("^MMOD 1 0\r");
		ser_.write("^MMOD 2 0\r");
		ser_.flush();
	}
	else{
		ser_.write("^MMOD 1 1\r");
		ser_.write("^MMOD 2 1\r");
		ser_.flush();
	}

	// 2026-11-15: 컨트롤러 속도 PID 가 공장 기본값(KP=KI=KD=0)이었음 — 매뉴얼 "Do not use default values. Use P=0, I=1, D=0
	//  in closed loop speed mode"(KP·KI 항목). 게인 0 이면 실제 속도가 모자라도 힘을 더 주지 않아 느린 제자리 회전에서 멈췄다
	//  튀는(덜컹·슬립) 원인. speed_pid_enable 일 때만 보냄. EEPROM 저장(%EESAV) 안 함 → 컨트롤러 전원을 끄면 원래 값으로.
	if (speed_pid_enable_ && closed_loop_){
		for (int ch = 1; ch <= 2; ++ch){
			std::stringstream g;
			g << "^KP " << ch << " " << static_cast<long>(speed_kp_ * 1e6) << "\r"
			  << "^KI " << ch << " " << static_cast<long>(speed_ki_ * 1e6) << "\r"
			  << "^KD " << ch << " " << static_cast<long>(speed_kd_ * 1e6) << "\r";
			ser_.write(g.str());
		}
		ser_.flush();
		RCLCPP_INFO(this->get_logger(), "[ROBOTEQ] 속도 PID 설정 보냄: P=%.3f I=%.3f D=%.3f (전원 끄면 원래대로)", speed_kp_, speed_ki_, speed_kd_);
	}

	std::stringstream right_enccmd;
	std::stringstream left_enccmd;
	right_enccmd << "^EPPR 1 " << 1024 << "\r";
	left_enccmd << "^EPPR 2 " << 1024 << "\r";
	ser_.write(right_enccmd.str());
	ser_.write(left_enccmd.str());
	ser_.flush();
}


// 2026-11-15: 느린 제자리 회전에서 바퀴가 앞뒤로 튀는(속도 제어 헌팅) 원인 조사 — 컨트롤러에 저장된 속도 제어 설정을
//  '읽기만' 해서(~ 명령, 값은 바꾸지 않음) 시작 로그에 남긴다. 이전 실행의 반복 보고(# 스크립트)를 먼저 멈춰 답이 섞이지 않게.
void RoboteqDriver::dumpConfig(){
	ser_.write("# C\r");
	ser_.flush();
	std::this_thread::sleep_for(std::chrono::milliseconds(200));
	if (ser_.available()) ser_.read(ser_.available());          // 남은 보고 버림
	const char* keys[] = {"MMOD", "KP", "KI", "KD", "BLFB", "MXRPM", "MAC", "MDEC", "ALIM", "ICAP",
	                      "CLERD", "EPPR", "EMOD", "BLSTD", "BPOL", "MXPF", "MXPR"};
	std::string all;
	for (auto k : keys){
		ser_.write(std::string("~") + k + "\r");
		ser_.flush();
		std::this_thread::sleep_for(std::chrono::milliseconds(80));
		std::string r;
		if (ser_.available()) r = ser_.read(ser_.available());
		boost::replace_all(r, "\r", " ");
		all += std::string(k) + "→[" + r + "] ";
	}
	RCLCPP_INFO_STREAM(this->get_logger(), tag << "컨트롤러 설정(읽기만): " << all);
}

void RoboteqDriver::run(){
	std::stringstream ss0, ss1;
	ss0 << "^echof 1_";
	ss1 << "# c_/\"DH?\",\"?\"";

	for (auto item : queries_){
		RCLCPP_INFO_STREAM(this->get_logger(),tag << "Publish topic: " << item.first);
		query_pub_.push_back(create_publisher<roboteq_interfaces::msg::ChannelValues>(item.first, 100));

		std::string cmd = item.second;
		ss1 << cmd << "_";
	}

	ss1 << "# " << frequency_ << "_";
	
	ser_.write(ss0.str());
	ser_.write(ss1.str());
	ser_.flush();
	

    serial_read_pub_ = create_publisher<std_msgs::msg::String>("read", rclcpp::SystemDefaultsQoS());

	std::chrono::duration<int, std::milli> dt (1000/frequency_);
	timer_pub_ = create_wall_timer(dt, std::bind(&RoboteqDriver::queryCallback, this) );
}


void RoboteqDriver::powerCmdCallback(const geometry_msgs::msg::Twist &msg){
	std::stringstream cmd_str;
	// [변경] 앞뒤양옆 180° 교체: 채널 1↔2 swap + 부호 반전
	// ch1(구 left) ← -right_value,  ch2(구 right) ← -left_value
	if (closed_loop_){
		cmd_str << "!S 1"
				<< " " << -msg.angular.z << "_"   // 구 ch2(right) → 부호 반전
				<< "!S 2"
				<< " " << -msg.linear.x << "_";   // 구 ch1(left)  → 부호 반전
	}
	else{
		cmd_str << "!G 1"
				<< " " << -msg.angular.z << "_"   // 구 ch2(right) → 부호 반전
				<< "!G 2"
				<< " " << -msg.linear.x << "_";   // 구 ch1(left)  → 부호 반전
	}
	ser_.write(cmd_str.str());
	ser_.flush();
	RCLCPP_INFO(this->get_logger(),"[ROBOTEQ] left: %9.3f right: %9.3f", msg.linear.x, msg.angular.z);
}


void RoboteqDriver::cmdVelCallback(const geometry_msgs::msg::Twist &msg){
	if (smooth_enable_){
		// 목표값만 갱신 — 실제 명령은 smoothStep() 이 가감속 한도 안에서 따라간다
		tgt_v_ = msg.linear.x;
		tgt_w_ = msg.angular.z;
		last_cmd_time_ = this->now();
		return;
	}
	sendWheelCommand(msg.linear.x, msg.angular.z);
}

static double clampAbs(double x, double lim){
	if (lim <= 0.0) return x;
	return std::max(-lim, std::min(lim, x));
}

void RoboteqDriver::joyCmdCallback(const geometry_msgs::msg::Twist &msg){
	if (!joy_active_){
		RCLCPP_INFO(this->get_logger(), "[ROBOTEQ] 조이스틱 조작 시작 → /cmd_vel(Nav2 등) 명령은 멈출 때까지 무시");
	}
	joy_v_ = msg.linear.x;
	joy_w_ = msg.angular.z;
	last_joy_time_ = this->now();
	joy_active_ = true;
	if (!smooth_enable_){
		sendWheelCommand(clampAbs(joy_v_, max_lin_vel_), clampAbs(joy_w_, max_ang_vel_));
	}
}

// 한 주기마다 현재 명령을 목표 쪽으로 한도만큼 움직인다. 크기가 줄거나 방향이 바뀌면 감속 한도, 커지면 가속 한도.
static double stepToward(double cur, double tgt, double acc, double dec, double dt){
	bool slowing = (std::fabs(tgt) < std::fabs(cur)) || (tgt * cur < 0.0);
	double lim = (slowing ? dec : acc) * dt;
	double d = tgt - cur;
	if (d > lim) d = lim;
	if (d < -lim) d = -lim;
	return cur + d;
}

void RoboteqDriver::smoothStep(){
	const double dt = 1.0 / std::max(1.0, smooth_rate_);
	const rclcpp::Time now = this->now();
	double tv, tw, la, ld, aa, ad;
	if (joy_active_){
		// 조이스틱 우선: 빠른 한도로 따라감. L1 놓으면 0 이 한 번 오고, 신호가 끊겨도 joy_timeout 뒤 0 으로.
		const double since = (now - last_joy_time_).seconds();
		tv = joy_v_; tw = joy_w_;
		if (since > joy_timeout_){ tv = 0.0; tw = 0.0; }
		la = joy_lin_acc_; ld = joy_lin_dec_; aa = joy_ang_acc_; ad = joy_ang_dec_;
		if (since > joy_timeout_ && cur_v_ == 0.0 && cur_w_ == 0.0){
			joy_active_ = false;       // 멈췄고 조이스틱 입력도 없음 → /cmd_vel 로 돌려줌
			RCLCPP_INFO(this->get_logger(), "[ROBOTEQ] 조이스틱 조작 끝(정지 확인) → /cmd_vel 입력으로 복귀");
		}
	}
	else{
		tv = tgt_v_; tw = tgt_w_;
		if ((now - last_cmd_time_).seconds() > cmd_timeout_){
			tv = 0.0; tw = 0.0;            // 명령이 끊기면 완만하게 정지
		}
		la = max_lin_acc_; ld = max_lin_dec_; aa = max_ang_acc_; ad = max_ang_dec_;
	}
	tv = clampAbs(tv, max_lin_vel_);
	tw = clampAbs(tw, max_ang_vel_);
	cur_v_ = stepToward(cur_v_, tv, la, ld, dt);
	cur_w_ = stepToward(cur_w_, tw, aa, ad, dt);
	if (std::fabs(cur_v_) < 1e-4) cur_v_ = 0.0;
	if (std::fabs(cur_w_) < 1e-4) cur_w_ = 0.0;
	bool zero = (cur_v_ == 0.0 && cur_w_ == 0.0);
	if (zero && sent_zero_) return;       // 정지 상태가 이어지면 다시 보내지 않음(시리얼 부하)
	sendWheelCommand(cur_v_, cur_w_);
	sent_zero_ = zero;
}

void RoboteqDriver::sendWheelCommand(double v, double w){
	float right_speed = v + track_width_ * w / 2.0;
	float left_speed  = v - track_width_ * w / 2.0;
	
	std::stringstream cmd_str;
	if (!closed_loop_){
		float right_power = right_speed *1000.0 *60.0/ (wheel_circumference_ * max_rpm_);
		float left_power  = left_speed  *1000.0 *60.0/ (wheel_circumference_ * max_rpm_);
	
		RCLCPP_DEBUG(this->get_logger(),"[ROBOTEQ] left: %9d right: %9d", (int)left_power, (int)right_power);   // 2026-11-13: INFO→DEBUG(매 명령 로그로 bringup.log 200MB+)
		
		// [변경] 앞뒤양옆 180° 교체: 채널 1↔2 swap + 부호 반전
		// 180° 회전 시: new_ch1 = -old_ch2(right), new_ch2 = -old_ch1(left)
		cmd_str << "!G 1"
				<< " " << -(int)right_power << "_"   // 구 right → ch1, 부호 반전
				<< "!G 2"
				<< " " << -(int)left_power << "_";   // 구 left  → ch2, 부호 반전
	}
	else{
		int32_t right_rpm = right_speed *60.0 / wheel_circumference_;
		int32_t left_rpm  = left_speed  *60.0 / wheel_circumference_;

		RCLCPP_DEBUG(this->get_logger(),"[ROBOTEQ] left: %9d right: %9d", left_rpm, right_rpm);   // 2026-11-13: INFO→DEBUG

		// [변경] 앞뒤양옆 180° 교체: 채널 1↔2 swap + 부호 반전
		cmd_str << "!S 1"
				<< " " << -right_rpm << "_"   // 구 right → ch1, 부호 반전
				<< "!S 2"
				<< " " << -left_rpm << "_";   // 구 left  → ch2, 부호 반전
	}

	ser_.write(cmd_str.str());
	ser_.flush();
}


void RoboteqDriver::queryCallback(){
	auto current_time = this->now();
	if (ser_.available()){
		std_msgs::msg::String result;

		std::lock_guard<std::mutex> lock(locker);

		result.data = ser_.read(ser_.available());

		serial_read_pub_->publish(result);
		
		boost::replace_all(result.data, "\r", "");
		boost::replace_all(result.data, "+", "");

		std::vector<std::string> fields;
		
		boost::split(fields, result.data, boost::algorithm::is_any_of("D"));
		if (fields.size() < 2){

			RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Empty data:{" << result.data << "}");
		}
		else if (fields.size() >= 2){
			std::vector<std::string> fields_H;
			for (int i = fields.size() - 1; i >= 0; i--){
				if (fields[i][0] == 'H'){
					try{
						fields_H.clear();
						boost::split(fields_H, fields[i], boost::algorithm::is_any_of("?"));
						if ( fields_H.size() >= query_pub_.size() + 1){
							break;
						}
					}
					catch (const std::exception &e){
						std::cerr << e.what() << '\n';
						RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Finding query output in :" << fields[i]);
						continue;
					}
				}
			}

			// 2026-11-12: 응답 두 개가 붙어 오는 등 깨진 데이터에서 필드 수가 질의 수보다 많으면
			//   query_pub_[i] 범위를 넘어 접근해 노드가 Segmentation fault(-11)로 죽었다 → 개수가 정확히 맞을 때만 처리.
			//   값 해석이 하나라도 실패한 채널은 발행하지 않는다(빈·반쪽 메시지가 diff_tf 를 죽였음).
			if (fields_H.size() > 0 && fields_H[0] == "H" && fields_H.size() - 1 != query_pub_.size()){
				RCLCPP_WARN_STREAM(this->get_logger(), tag << "필드 수 불일치(" << fields_H.size() - 1 << " vs "
				                   << query_pub_.size() << ") → 이번 응답 버림");
			}
			else if (fields_H.size() > 0 && fields_H[0] == "H"){
				for (size_t i = 0; i + 1 < fields_H.size() && i < query_pub_.size(); ++i){
					std::vector<std::string> sub_fields_H;
					boost::split(sub_fields_H, fields_H[i + 1], boost::algorithm::is_any_of(":"));
					
					roboteq_interfaces::msg::ChannelValues msg;
					msg.header.stamp = current_time;
					bool ok = true;

					for (size_t j = 0; j < sub_fields_H.size(); j++){
						try{
							int v = boost::lexical_cast<int>(sub_fields_H[j]);
							msg.value.push_back(v);   // raw 엔코더 출력 전체 반전
						}
						catch (const std::exception &e){
							ok = false;
							RCLCPP_ERROR_STREAM(this->get_logger(),tag << "Garbage data on Serial");
							RCLCPP_ERROR_STREAM(this->get_logger(), result.data);
							RCLCPP_ERROR_STREAM(this->get_logger(), e.what());
						}
					}
					if (ok && !msg.value.empty()){
						query_pub_[i]->publish(msg);
					}
				}
			}
		}
		else{
			RCLCPP_WARN_STREAM(this->get_logger(),tag << "Unknown:{" << result.data << "}");
		}
	}
}


int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<RoboteqDriver>());
  rclcpp::shutdown();
  return 0;
}
