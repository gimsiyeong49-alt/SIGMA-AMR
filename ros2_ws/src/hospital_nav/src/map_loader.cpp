#include "hospital_nav/map_loader.hpp"
#include <yaml-cpp/yaml.h>
#include <fstream>
#include <stdexcept>

namespace hospital_nav {

MapLoader::MapLoader(const rclcpp::NodeOptions & options)
: Node("map_loader", options)
{
    declare_parameter("map_yaml_path", "");
    std::string yaml_path = get_parameter("map_yaml_path").as_string();

    if (yaml_path.empty()) {
        RCLCPP_ERROR(get_logger(), "map_yaml_path 파라미터가 비어있음");
        return;
    }

    rclcpp::QoS qos(1);
    qos.transient_local();
    qos.reliable();
    map_pub_ = create_publisher<nav_msgs::msg::OccupancyGrid>("/map", qos);

    loadMap(yaml_path);

    // transient_local 이므로 1회 publish면 늦게 뜬 subscriber도 수신 가능
    map_msg_.header.stamp = now();
    map_pub_->publish(map_msg_);

    RCLCPP_INFO(get_logger(), "Map loaded and published once on /map (transient_local)");
}

void MapLoader::loadMap(const std::string & yaml_path)
{
    YAML::Node config = YAML::LoadFile(yaml_path);

    double resolution = config["resolution"].as<double>();
    auto origin_vec   = config["origin"].as<std::vector<double>>();

    std::string pgm_name = config["image"].as<std::string>();
    std::string base_dir = yaml_path.substr(0, yaml_path.find_last_of("/\\"));
    std::string pgm_path = base_dir + "/" + pgm_name;

    parsePgm(pgm_path, map_msg_);

    map_msg_.info.resolution = resolution;
    map_msg_.info.origin.position.x = origin_vec[0];
    map_msg_.info.origin.position.y = origin_vec[1];
    map_msg_.info.origin.position.z = 0.0;
    map_msg_.info.origin.orientation.w = 1.0;
    map_msg_.header.frame_id = "map";
    map_msg_.header.stamp = now();
}

bool MapLoader::parsePgm(const std::string & pgm_path,
                          nav_msgs::msg::OccupancyGrid & grid)
{
    std::ifstream file(pgm_path, std::ios::binary);
    if (!file.is_open()) {
        throw std::runtime_error("PGM 파일 열기 실패: " + pgm_path);
    }

    std::string magic;
    file >> magic;

    std::string line;
    std::getline(file, line);
    while (file.peek() == '#') std::getline(file, line);

    int width, height, max_val;
    file >> width >> height >> max_val;
    file.get();

    grid.info.width  = width;
    grid.info.height = height;
    grid.data.resize(width * height);

    if (magic == "P5") {
        std::vector<uint8_t> raw(width * height);
        file.read(reinterpret_cast<char*>(raw.data()), raw.size());

        for (int row = 0; row < height; row++) {
            int flipped_row = height - 1 - row;
            for (int col = 0; col < width; col++) {
                uint8_t pixel = raw[row * width + col];
                double val = pixel / 255.0;

                int idx = flipped_row * width + col;
                if (val > 0.65)       grid.data[idx] = 0;
                else if (val < 0.25)  grid.data[idx] = 100;
                else                  grid.data[idx] = -1;
            }
        }
    }

    return true;
}

} // namespace hospital_nav

int main(int argc, char ** argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<hospital_nav::MapLoader>());
    rclcpp::shutdown();
    return 0;
}
