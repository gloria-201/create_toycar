This project is built on ROS Melodic

------------------------------  
   Clone the following repos first:
   rplidar drive: 
   git clone https://github.com/Slamtec/rplidar_ros.git
 
   yolov5 real-time object detection:
   git clone https://github.com/ultralytics/yolov5
 
   Asr_ftc_local_planner
   git clone --branch melodic https://github.com/asr-ros/asr_ftc_local_planner.git
   git clone --branch melodic https://github.com/asr-ros/asr_move_base.git
   git clone --branch melodic https://github.com/asr-ros/asr_nav_core.git
------------------------------ 
------------------------------
  The iRobot Create 2 drive packages are from the repo:  https://github.com/AutonomyLab/create_robot.git , My repo add 2 msg file in create_msgs
   git clone https://github.com/gloria-201/create_toycar.git
   catkin build
------------------------------
------------------------------
Make sure the navigation part works correct:
   roslaunch create_navigation test_nav.launch
------------------------------
------------------------------
Launch the detection part with:
   roslaunch push_toy_car push_toycar.launch
------------------------------
------------------------------
You can tune the parameters in /push_toycar/config/push_toycar_params.yaml
Or change your own training model with /push_toycar/model/best.pt

Find the pixel coordinates for docking with /push_toycar/test/image_pixel.py 
(note:written with Python3)

Change your own camera intrinsic and extrinsic parameters in /push_toycar/camera_params to make sure the right frame transformation 
