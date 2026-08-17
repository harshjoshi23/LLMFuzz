# PSOC&trade; Control C3P(M)5: DC optimizer

This code example works with Infineon's REF_OPTI_80V20A_GaN board, which has the PSOC&trade; Control C3M5 device, a debugger, UART, power stage, and passive components. It is designed to demonstrate the capabilities of Infineon's GaN switches and PSOC&trade; Control C3M5 microcontroller for power control applications.


## Requirements

- [ModusToolbox&trade;](https://www.infineon.com/modustoolbox) v3.5, v3.6, or v3.7
- Board support package (BSP) minimum required version for : 3.0.1
- Hardware target evaluation: REF_OPTI_80V20A_GaN: v2.0
- Programming language: C
- Associated parts: All PSOC&trade; Control C3 MCU parts


## Supported toolchains (make variable 'TOOLCHAIN')

- GNU Arm&reg; Embedded Compiler v11.3.1 (`GCC_ARM`) – Default value of `TOOLCHAIN`
- Arm&reg; Compiler v6.22 (ARM)
- IAR C/C++ Compiler v9.50.2 (IAR)


## Supported kits (make variable 'TARGET')

- [PSOC&trade; Control C3M5 Compact Kit](https://www.infineon.com/evaluation-board/REF-OPTI-80V20A-GAN) (`REF_OPTI_80V20A_GaN`)


## Hardware setup

This example uses DC optimizer board for solar applications. The configurations are based on the hardware schematics of the board.


## Software setup

See the [ModusToolbox&trade; tools package installation guide](https://www.infineon.com/ModusToolboxInstallguide) for information about installing and configuring the tools package.


Install a terminal emulator if you do not have one. Instructions in this document use [Tera Term](https://ttssh2.osdn.jp/index.html.en).

The debug is performed in two ways. One using a serial terminal, such as Tera Term.

The other option is to use OneEye GUI, which you can download from [here](https://softwaretools.infineon.com/tools/com.ifx.tb.tool.oneeye3).

This example requires no additional software or tools.


## Using the code example


### Create the project

The ModusToolbox&trade; tools package provides the Project Creator as both a GUI tool and a command line tool.

<details><summary><b>Use Project Creator GUI</b></summary>

1. Open the Project Creator GUI tool

   There are several ways to do this, including launching it from the dashboard or from inside the Eclipse IDE. For more details, see the [Project Creator user guide](https://www.infineon.com/ModusToolboxProjectCreator) (locally available at *{ModusToolbox&trade; install directory}/tools_{version}/project-creator/docs/project-creator.pdf*)

2. On the **Choose Board Support Package (BSP)** page, select a kit supported by this code example. See [Supported kits](#supported-kits-make-variable-target)

   > **Note:** To use this code example for a kit not listed here, you may need to update the source files. If the kit does not have the required resources, the application may not work

3. On the **Select Application** page:

   a. Select the **Applications(s) Root Path** and the **Target IDE**

      > **Note:** Depending on how you open the Project Creator tool, these fields may be pre-selected for you

   b. Select this code example from the list by enabling its check box

      > **Note:** You can narrow the list of displayed examples by typing in the filter box

   c. (Optional) Change the suggested **New Application Name** and **New BSP Name**

   d. Click **Create** to complete the application creation process

</details>


<details><summary><b>Use Project Creator CLI</b></summary>

The 'project-creator-cli' tool can be used to create applications from a CLI terminal or from within batch files or shell scripts. This tool is available in the *{ModusToolbox&trade; install directory}/tools_{version}/project-creator/* directory.

Use a CLI terminal to invoke the 'project-creator-cli' tool. On Windows, use the command-line 'modus-shell' program provided in the ModusToolbox&trade; installation instead of a standard Windows command-line application. This shell provides access to all ModusToolbox&trade; tools. You can access it by typing "modus-shell" in the search box in the Windows menu. In Linux and macOS, you can use any terminal application.

The following example clones the "[DC Optimizer](https://github.com/Infineon/mtb-example-pwrlib-dc-optimizer)" application with the desired name "mtb-example-dcoptimizer" configured for the *REF_OPTI_80V20A_GaN* BSP into the specified working directory, *C:/mtb_projects*:

   ```
   project-creator-cli --board-id REF_OPTI_80V20A_GaN --app-id mtb-example-ce240786-empty-app --user-app-name MyEmptyApp --target-dir "C:/mtb_projects"
   ```

The 'project-creator-cli' tool has the following arguments:

Argument | Description | Required/optional
---------|-------------|-----------
`--board-id` | Defined in the <id> field of the [BSP](https://github.com/Infineon?q=bsp-manifest&type=&language=&sort=) manifest | Required
`--app-id`   | Defined in the <id> field of the [CE](https://github.com/Infineon?q=ce-manifest&type=&language=&sort=) manifest | Required
`--target-dir`| Specify the directory in which the application is to be created if you prefer not to use the default current working directory | Optional
`--user-app-name`| Specify the name of the application if you prefer to have a name other than the example's default name | Optional

<br>

> **Note:** The project-creator-cli tool uses the `git clone` and `make getlibs` commands to fetch the repository and import the required libraries. For details, see the "Project creator tools" section of the [ModusToolbox&trade; tools package user guide](https://www.infineon.com/ModusToolboxUserGuide) (locally available at {ModusToolbox&trade; install directory}/docs_{version}/mtb_user_guide.pdf).

</details>


### Open the project

After the project has been created, you can open it in your preferred development environment.


<details><summary><b>Eclipse IDE</b></summary>

If you opened the Project Creator tool from the included Eclipse IDE, the project will open in Eclipse automatically.

For more details, see the [Eclipse IDE for ModusToolbox&trade; user guide](https://www.infineon.com/MTBEclipseIDEUserGuide) (locally available at *{ModusToolbox&trade; install directory}/docs_{version}/mt_ide_user_guide.pdf*).

</details>


<details><summary><b>Visual Studio (VS) Code</b></summary>

Launch VS Code manually, and then open the generated *{project-name}.code-workspace* file located in the project directory.

For more details, see the [Visual Studio Code for ModusToolbox&trade; user guide](https://www.infineon.com/MTBVSCodeUserGuide) (locally available at *{ModusToolbox&trade; install directory}/docs_{version}/mt_vscode_user_guide.pdf*).

</details>



<details><summary><b>Command line</b></summary>

If you prefer to use the CLI, open the appropriate terminal, and navigate to the project directory. On Windows, use the command-line 'modus-shell' program; on Linux and macOS, you can use any terminal application. From there, you can run various `make` commands.

For more details, see the [ModusToolbox&trade; tools package user guide](https://www.infineon.com/ModusToolboxUserGuide) (locally available at *{ModusToolbox&trade; install directory}/docs_{version}/mtb_user_guide.pdf*).

</details>

## Operation

1. Connect the board to your PC using the provided USB cable through the external JLink USB connector

2. Program the board using one of the following:

   <details><summary><b>Using Eclipse IDE</b></summary>

      1. Select the application project in the Project Explorer

      2. In the **Quick Panel**, scroll down, and click **mtb-example-pwrlib-dc-optimzer Program (JLink)**
   </details>


   <details><summary><b>In other IDEs</b></summary>

   Follow the instructions in your preferred IDE
   </details>


   <details><summary><b>Using CLI</b></summary>

     From the terminal, execute the `make program` command to build and program the application using the default toolchain to the default target. The default toolchain is specified in the application's Makefile but you can override this value manually:
      ```
      make program TOOLCHAIN=<toolchain>
      ```

      Example:
      ```
      make program TOOLCHAIN=GCC_ARM
      ```
   </details>

   The Arm&reg; and IAR compilers are also supported for this application. To switch to ARM compiler mention the TOOLCHAIN  = ARM , also provide the path using the variable CY_COMPILER_IAR_DIR.
   
   <details><summary><b>Known issue for TOOLCHAIN=ARM MTB v3.7 and earlier</b></summary>

     There is a known issue with the ARM compiler in MTB version 3.7 and earlier. As a workaround, add the following post-build step to your BSP Makefile (bsp.mk) before the "Enable JLink debugger" section :
      ```
      bsp_postbuild:
      ifneq ($(CY_TOOL_edgeprotecttools_EXE_ABS),)
      $(CY_TOOL_edgeprotecttools_EXE_ABS) hex-relocate --region 0x12000000 0x00040000 0x32000000 -i $(_MTB_RECIPE__PROG_FILE) -o $(_MTB_RECIPE__PROG_FILE)
      else
      $(MTB__NOISE)echo
      $(MTB__NOISE)echo "Error: EdgeProtect Secure Suite not found. Hex-relocation step not executed."
      $(MTB__NOISE)echo "Run the ModusToolbox Setup program to install the Edge Protect Security suite."
      $(MTB__NOISE)echo
      $(MTB__NOISE)exit 1
      endif
      ```
   </details>

3. If you select **DCO_DEBUG_MODE_SELECTION** as **DCO_UI_SERIAL_ANALYZER**, open the serial terminal provide the corresponding COM Port and set the serial port parameters to 8N1 and 115200 baud. After programming, the application starts automatically. Confirm that "PSoC Control C3M5 MCU: Code Example for DC Optimizer" is displayed on the UART terminal

   Or,
   
   If you select **DCO_DEBUG_MODE_SELECTION** as **DCO_UI_ONE_EYEGUI**, 
      1. Open the OneEye GUI and click on the file, Load Configuration and load the *DC_Optimzer_REF_Opti_80V_20A.OneEye* file from the *oneeye* folder
      
      2. Press **setup serial interface** and select the device as **Jlink**, set baud rate as 115200 and press connect. The GUI shows the mode of operation and state of the converter
      
      3. Now, if sufficient input voltage is provided, press the enable switch from the board or the **Start** button from the GUI; the converter operates based on the selected mode
      
      5. Confirm that STEADY state is reached in GUI or Tera Term


## Debugging

You can use the teraterm output to analyze the behavior based on the errors having reported.

You can debug the example to step through the code.


<details><summary><b>In Eclipse IDE</b></summary>

Use the **DC Optimizer_PFC Debug (JLink)** configuration in the **Quick Panel**.

For details, see the "Program and debug" section in the [Eclipse IDE for ModusToolbox&trade; user guide](https://www.infineon.com/MTBEclipseIDEUserGuide).


</details>


<details><summary><b>In other IDEs</b></summary>

Follow the instructions in your preferred IDE.

</details>


# DC Optimizer controller overview

The DC optimizer demonstrates the working of buck converter in different modes implemented on  Infineon's PSOC&trade; Control C3M5FDS2LGQ1 MCU. This example delivers a highly efficient DC-DC power conversion for various modes for various modes achievable in a buck converter.

Its key features include:

- Open loop mode with soft start
- Average output current control mode
- Voltage control mode
- MPPT control mode
- Advanced state machine for precise operational control

Comprehensive protection mechanisms:

- Input undervoltage and overvoltage protection
- Input and output overcurrent protection
- Overtemperature protection
- Brown-in/Brown-out handling for safe startup and shutdown
- System fault detection for robust safety


## Controller operation and key features

The DC optimizer controller starts its operation with a robust, event-driven startup sequence orchestrated by a functional state machine. Upon power up, the system initializes all peripherals and parameters and enables an interrupt to occur every 1 ms using a PWM counter (TCPWM [0] Group [0] Counter 1). This interrupt calls a scheduler in which the state machine executes. 

- **Entry action (pfc_state_machine_entry_action):** Runs once upon entering a new state to manage the transition into new state with proper initialization

  - Hardware configuration: Sets up appropriate hardware parameters for each state
  - Safety setup: Configures protection thresholds appropriate to each operational mode
  - Controller initialization: Prepares control loops with suitable parameters
  - Visual indicators: Updates status LEDs to reflect current system state
  - Power path control: Manages power flow through relays and switching phases

- **Do Action (pfc_state_machine_do_action):** Runs continuously to monitor conditions and manage transitions

  - State-dependent processing (SDP): Executes control loops specific to each state
  - State-dependent evaluation (SDE): Continuously monitors for events (voltages, currents, faults, etc.) that might require state transitions
  - State-dependent transitions (SDT): Evaluates condition- and trigger-appropriate state changes based on events or protection triggers
  - Protection handling: Continuously checks for fault conditions with priority handling
  - System synchronization: Aligns operations with AC zero crossings and polarity changes

**Figure 1. Controller operation and key features**

![Controller operation and key features](images/DC_Optimizer_State_Machine.jpg "State Machine Diagram for DC Optimizer")

The state machine consists of the following states:

-	DCO_STATE_OFF
-	DCO_STATE_PASSIVE
-	DCO_STATE_STEADY
-	DCO_STATE_PROTECTION_LATCH


### DCO_STATE_OFF

The state machine starts in DCO_STATE_OFF. The state machine takes the function to entry action. The entry actions enter once during the state changes. Here, the variables are configured to its initial value. At the next ISR (after 1 ms), the state machine takes the program to do_action, where the state checks for the ON command. 

The ON command can be received in two ways, first is through an enable switch connected to GPIO 2. When a low transition is detected, an interrupt is generated and takes to a `Dco_SwitchHandler`function, which sets the utility flag to DCO_UTILITY_ENABLE_POWER_CONV, which in turn, takes the state to DCO_STATE_PASSIVE.

You can also switch on the converter using the OneEye GUI. When you press the enable switch through the GUI, the function `Dco_EnDisPowerConversionOneEye` executes and sets the same utility flag, DCO_UTILITY_ENABLE_POWER_CONV, and transitions into the DCO_STATE_PASSIVE state.


### DCO_STATE_PASSIVE

When the state machine enters the DCO_STATE_PASSIVE state, its entry action runs once. In this state, the temperature and voltage brown-in counters are initialized. At the next ISR tick (1 ms later), the state machine executes the do_action passive state. In the do_action passive state temperature, the input voltage is monitored. If the input voltage is less than the DCO_VPV_MIN_V macro, the state continues to be in passive state. If the input voltages and temperatures are normal, the state moves to DCO_STATE_STEADY. If the converter gets some protection events, the state moves to DCO_STATE_PROTECTION_LATCH. 


### DCO_STATE_STEADY

The DC optimizer is run in the following modes: DCO_MODE_OPEN_LOOP, DCO_MODE_INNER_CURRENT_CONTROL, DCO_MODE_VOLTAGE_CONTROL, DCO_MODE_MPPT_CONTROL based on the DCO_MODE_SELECTION macro.  


#### DCO_MODE_OPEN_LOOP

This mode represents the open loop mode. You can set the final duty ratio of the converter in open loop using DCO_PWM_DUTY_RATIO and the acceleration rate using DCO_RAMP_RATE macros. At the end of the entry action, the TCPWM[0] Group[0] 32 bit Counter 3 (PWM_Gen) is started. The central-aligned PWM is used for PWM generation. At the midpoint of this PWM Counter, an ADC start of conversion is generated using trigger outputs. An average of eight samples are configured for output voltage and output current. At the end of eight samples, the end-of-conversion ADC interrupt is generated, which calls the `Dco_3P3ZControlHandler` function. In this function, the output currents and voltages are read from the ADC registers. It also loads the compare value into the Buffer register to generate the PWMs in open loop mode. 

**Figure 2. Open loop mode** 

![Open Loop mode](images/open_loop_mode.jpg "Open Loop mode")


#### DCO_MODE_INNER_CURRENT_CONTROL

If you select DCO_MODE_SELECTION as DCO_MODE_INNER_CURRENT_CONTROL, the buck converter is initialized to operate in output average current control mode from DCO_STATE_STEADY. This means the duty ratio will be generated to pass the set output current using the macro DCO_IL_REF_A. You can choose the DCO_IL_KP and DCO_IL_KI controller constants to achieve the desired response of the current loop. Further, the control is implemented in 3P 3Z generalized format. The final duty ratio from inner current control is loaded into the buffer registers from the control ISR, i.e, `Dco_3P3ZControlHandler`.

**Figure 3. Current control mode**

![Current Control Mode](images/current_control_mode.jpg "Current Control Mode")


#### DCO_MODE_VOLTAGE_CONTROL

If you select DCO_MODE_SELECTION as DCO_MODE_VOLTAGE_CONTROL, the buck converter is initialized to operate in the output voltage control mode or standard buck mode from DCO_STATE_STEADY. Set the output reference voltage using DCO_VOUT_REF_V and provide the maximum reference current to be controlled by the inner current loop using DCO_IL_REF_MAX_A.  You can choose the DCO_IL_KP, DCO_IL_KI, DCO_VOUT_KP, and DCO_VOUT_KI controller constants to achieve the desired response of the voltage loop. This control method is like a typical outer voltage loop followed by an inner current control. Further, the control is implemented in 3P 3Z generalized format. The 3P 3Z calculations are called every 50 kHz and the duty ratio received from 3P 3Z are loaded into the buffer registers of the PWM counter.

**Figure 4. Voltage control mode**

![Voltage Control Mode](images/voltage_control_mode.jpg "Voltage Control Mode")


####	DCO_MODE_MPPT_CONTROL

Unlike a voltage control mode, the MPPT mode regulates the input voltage for the solar panel to extract maximum power. The duty ratio is generated so the buck converter input resistances matches the load resistance. By increasing the duty cycle, the output current rises, which in turn increases the input current, leading to a drop in the input voltage. The input power is measured on every DCO_MPPT_DELAY (30 ms), a working point with highest possible input power is reached. In this optimizer, the MPPT algorithm gives the reference voltage feedback to the voltage control loop and voltage control loop in turn generates the duty ratio. The perturb and observe algorithm is used for MPPT and 3P3Z controllers are used for voltage control. The MPPT algorithm executes every 30 ms and the voltage loop works at every 50 kHz. This leads to a very quick response time in case the load or input power changes.

**Figure 5. Perturb and observe algorithm**

![MPPT Control Mode](images/P_O_Algo.jpg "Perturb and Algo")  

The step size of the reference voltage DCO_VPV_STEP_V is set to ~0.4 V in order to quickly track the target voltage in case of shadowing, but still accurately reach the maximum power point. The MPPT algorithm gives the reference input voltage. The voltage loop regulates in order to achieve this input voltage. The firmware itself can be adapted to also fit for other voltage and current ranges by various macros, whose descriptions are given below.


**Figure 6. MPPT control mode**

![MPPT Control Mode](images/mppt_control_mode.jpg "MPPT Control Mode")


####	DCO_STATE_PROTECTION_LATCH

At every state, the input voltage, input current, output current, and temperature are monitored. If any of these parameters exceed their defined limits, the state machine immediately transitions to DCO_STATE_PROTECTION_LATCH. When a protection latch occurs, restart the controller.


## MCU peripherals configuration

The DC optimizer code example is implemented on the Infineon PSOC&trade; Control C3M5 MCU, with all hardware configuration managed using the ModusToolbox&trade; Device Configurator. The configuration file *design.modus* contains all user-defined settings for MCU peripherals, pin assignments, and hardware features, making the setup transparent and reproducible. 

**Figure 7. Device configurator**

![Device Configurator](images/Modus_Config.png "Device Configurator")

The table below lists all the MCU hardware used for DC Optimizer PFC application.


**Table 1. Hardware utilization**

**Used peripheral**                              | **Description**
-------------------------------------------------|------------------------------------------------------------------------------------------------------------------
DEBUG_UART                                       | For data transfer to host PC
P4[0] (PWMUH_P, PWM, GPIO), P4[1] (PWMUL_P, PWM, GPIO) | High-frequency PWM driving high/low side power switches
AN_A0 (Temp)                                     | Measures the PCB temperature
AN_A1 (I_in)                                     | Measures the input current of the DC optimizer
AN_A2 (V_in)                                     | Measures input voltage
AN_A3 (I_out)                                    | Measures the output inductor current
AN_A4 (V_out)                                    | Measures the output voltage of the converter
CMP_BUCK_IN_CURR (CSG), CMP_BUCK_OUT_CURR (CSG)  | Hardware analog comparators monitoring input and output overcurrent; trigger protection events via CSG
P2[0] (GPIO Input)                               | Enable switch to start the converter

<br>


##	Application software configuration

The DC optimizer firmware provides configurability to adapt the controller for various hardware configurations, power ranges, and component technologies. This flexibility enables you to fine tune the existing system or adapt it to entirely different hardware platforms with minimal firmware modifications.
The following table outlines the key parameters you can adjust to optimize performance or port the design to different DC-DC converter applications.


**Table 2. DC optimizer parameters**

**Parameter**                  | **Default Value**    | **Unit** | **Description**                                                                
-------------------------------|----------------------|----------|--------------------------------------------------------------------------------
DCO_MODE_SELECTION             | DCO_MODE_SELECTION   | -        | Helps to select the mode of operation of DC optimizer               
DCO_UI_MODE_SELECTION          | DCO_UI_MODE_SELECTION | -       | Allows you to select either the OneEye GUI or serial analyzer for debugging purpose
DCO_SCHEDULER_FREQ             | 1                    | kHz      | Sets the scheduler frequency
DCO_IPV_OCP_HW_THRESHOLD_A     | 30                   | A        | Input overcurrent protection threshold
DCO_IL_OCP_HW_THRESHOLD_A      | 30                   | A        | Output overcurrent protection threshold
DCO_IL_ADC_CONVERSION_FACTOR   | 0.009827571          | -        | Output current (A) to digital data conversion factor for Il
DCO_IPV_ADC_CONVERSION_FACTOR  | 0.009827571          | -        | Input current (A) to digital data conversion factor for Ipv                     
DCO_VOUT_ADC_CONVERSION_FACTOR | 0.02138103           | -        | Voltage to digital data conversion factor for output voltage 
DCO_VPV_ADC_CONVERSION_FACTOR  | 0.02138103           | -        | Voltage to digital data conversion factor for input voltage                     
DCO_TEMP_ADC_CONVERSION_FACTOR | 0.000805861          | -        | Voltage to digital counts conversion factor for temperature                     
DCO_PWM_DUTY_RATIO             | 0.5                  | -        | Steady state duty ratio for open loop                                           
DCO_RAMP_RATE                  | 0.1                  | s        | Ramp rate for open loop                                                         
DCO_IL_REF_A                   | 4.0                  | A        | Reference current for current control mode                                      
DCO_PWM_DUTY_RATIO_MAX         | 0.99                 | -        | Maximum duty ratio set by inner loop                                            
DCO_PWM_DUTY_RATIO_MIN         | 0.05                 | -        | Minimum duty ratio set by inner loop                                            
DCO_VOUT_REF_V                 | 20.0                 | V        | Reference output voltage for buck mode                                          
DCO_IL_REF_MAX_A               | 20.0                 | A        | Maximum reference Il for current loop                                           
DCO_PIN_STEP_W                 | 1.0                  | W        | Dead band of power for which variation in Vref is not required                  
DCO_VPV_MAX_V                  | 85.0                 | V        | Maximum input voltage                                                           
DCO_VPV_MIN_V                  | 12.0                 | V        | Minimum input voltage                                                           
DCO_VPV_STEP_V                 | 0.3                  | V        | The voltage step required to track the MPPT                                     
DCO_INTIAL_DELTA_V             | 4.0                  | V        | The initial voltage difference to kickstart the MPPT algorithm                     
DCO_IL_B0                      | 0.0018               | -        | Coefficient for designed current loop                                           
DCO_IL_B1                      | -0.0016              | -        | Coefficient for designed current loop                                           
DCO_VOUT_B0                    | 0.05                 | -        | Coefficient for voltage current loop                                            
DCO_VOUT_B1                    | -0.049               | -        | Coefficient for voltage current loop
DCO_VPV_BROWN_IN_DELAY         | 200000               | ms       | Vpv minimum brown-in period
DCO_VPV_BROWN_OUT_DELAY        | 200000               | ms       | Vpv minimum brown-output period
DCO_PTC_OVER_TEMP_DELAY        | 500000               | ms       | Overtemperature counter
DCO_MPPT_DELAY                 | 30000                | ms       | MPPT scheduler time
DCO_PTC_OVER_TEMP_THRESHOLD    | 90                   | C        | Overtemperature threshold

<br>


##	 Test results and measurements


### Open loop mode

If you select DCO_MODE_SELECTION as DCO_MODE_OPEN_LOOP, the converter operates in open loop mode. The duty ratio is ramped as defined by DCO_RAMP_RATE and reaches a steady state value of DCO_PWM_DUTY_RATIO. 

**Figure 8. Test results – Open loop mode**

![Open Loop Mode](images/Open_Loop.jpg "Open Loop Mode")

![Open Loop Mode](images/Open_Loop_Duty_ratio.png "Open Loop Mode")


### Current Control Mode

If you select DCO_MODE_SELECTION as DCO_MODE_INNER_CURRENT_CONTROL, the converter operates the outer current model. Set the target DCO_IL_REF_A shall. The duty ratio is generated to pass the reference current you set. 

**Figure 10. Test results – Current control mode**

![Current Control Mode](images/Current_Control_One_Eye_GUI.jpg "Current Control Mode")

![Current Control Mode](images/Current_Control_Mode.png "Current Control Mode")


### Output voltage control mode

If you select DCO_MODE_SELECTION as DCO_MODE_VOLTAGE_CONTROL, the converter operates in output voltage control or buck mode. Set the target DCO_VOUT_REF_V. The duty ratio is generated to set the reference voltage you set.  

**Figure 11. Test results – Output voltage control mode**

![Output Voltage Control Mode](images/Voltage_Control_OneEye_GUI.jpg "Output Voltage Control Mode")

![Output Voltage Control Mode](images/Voltage_Response.png "Output Voltage Control Mode")


### MPPT control mode

If you select DCO_MODE_SELECTION as DCO_MODE_MPPT_CONTROL, the converter operates in the MPPT control mode. You can set the following macros: DCO_PIN_STEP_W, DCO_VPV_MAX_V, DCO_VPV_MIN_V, DCO_VPV_STEP_V, and DCO_INTIAL_DELTA_V for MPPT control modes. 

**Figure 12. Test results – MPPT control mode**

![MPPT Control Mode](images/MPPT_Control_Mode_One_Eye_GUI.jpg "MPPT Control Mode")

![MPPT Control Mode](images/MPPT_Tracking.jpg "MPPT Control Mode")


## Summary

This firmware note presents the design, implementation, and performance evaluation of a DC optimizer, developed on REF_OPTI_80V20A_GaN evaluation board that is based on the PSOC&trade; Control C3M5 device. The system features a fully digital control approach based on a PSOC&trade; Control C3M5 microcontroller and leverages Infineon’s latest power semiconductor technologies, including CoolSiC&trade; and CoolMOS&trade; devices.

This platform provides a robust and scalable reference design for developers seeking to implement high-performance DC-DC different working modes. 


## Related resources

Resources  | Links
-----------|----------------------------------
Getting started user guide | [UG162027](https://www.infineon.com/assets/row/public/documents/24/44/infineon-coolgan-solar-optimizer-with-gan-transistors-in-a-buck-configuration-firmware-configuration-guide-usermanual-en.pdf) – Solar optimizer with CoolGaN&trade; transistors in a buck configuration: Firmware configuration guide
Firmware controller user guide | [UG153123](https://www.infineon.com/assets/row/public/documents/24/44/infineon-coolgan-solar-optimizer-transistors-in-a-buck-configuration-controller-guide-usermanual-en.pdf) – Solar optimizer with CoolGaN&trade; transistors in a buck configuration: Controller guide
Reference board user guide | [UG151649](https://www.infineon.com/assets/row/public/documents/24/44/infineon-ref-opti-80v20a-gan-usermanual-en.pdf) – Solar optimizer with CoolGaN&trade; transistors in a buck configuration
Application notes  | [AN238329](https://www.infineon.com/assets/row/public/documents/30/42/infineon-an238329-getting-started-psoc-control-c3-modustoolbox-applicationnotes-en.pdf?fileId=8ac78c8c92bcf0b0019393f072d813b5) – Getting started with PSOC&trade; Control C3 MCU on ModusToolbox&trade; software
Code examples  | [Using ModusToolbox&trade;](https://github.com/Infineon/Code-Examples-for-ModusToolbox-Software) on GitHub
Device documentation | [PSOC&trade; Control C3 MCU datasheet](https://www.infineon.com/cms/en/product/microcontroller/32-bit-psoc-arm-cortex-microcontroller/32-bit-psoc-control-arm-cortex-m33-mcu/psoc-control-c3p/#!documents) <br> [PSOC&trade; Control C3 technical reference manuals](https://www.infineon.com/cms/en/product/microcontroller/32-bit-psoc-arm-cortex-microcontroller/32-bit-psoc-control-arm-cortex-m33-mcu/psoc-control-c3p/#!documents)
Development kits | Select your kits from the [Evaluation board finder](https://www.infineon.com/cms/en/design-support/finder-selection-tools/product-finder/evaluation-board)
Libraries on GitHub  | [mtb-pdl-cat1](https://github.com/Infineon/mtb-pdl-cat1) – Peripheral Driver Library (PDL) <br> [mtb-hal-psc3](https://github.com/Infineon/mtb-hal-psc3) – Hardware Abstraction Layer (HAL) library <br> [retarget-io](https://github.com/Infineon/retarget-io) – Utility library to retarget STDIO messages to a UART port
Tools  | [ModusToolbox&trade;](https://www.infineon.com/modustoolbox) – ModusToolbox&trade; software is a collection of easy-to-use libraries and tools enabling rapid development with Infineon MCUs for applications ranging from wireless and cloud-connected systems, edge AI/ML, embedded sense and control, to wired USB connectivity using PSOC&trade; Industrial/IoT MCUs, AIROC&trade; Wi-Fi and Bluetooth&reg; connectivity devices, XMC&trade; Industrial MCUs, and EZ-USB&trade;/EZ-PD&trade; wired connectivity controllers. ModusToolbox&trade; incorporates a comprehensive set of BSPs, HAL, libraries, configuration tools, and provides support for industry-standard IDEs to fast-track your embedded application development

<br>


## Other resources

Infineon provides a wealth of data at [www.infineon.com](https://www.infineon.com) to help you select the right device, and quickly and effectively integrate it into your design.


## Document history

Document title: *CE240786* – *PSOC&trade; Control C3P(M)5: DC optimizer*

 Version | Description of change
 ------- | ---------------------
 1.0.0   | New code example

<br>


All referenced product or service names and trademarks are the property of their respective owners.

The Bluetooth&reg; word mark and logos are registered trademarks owned by Bluetooth SIG, Inc., and any use of such marks by Infineon is under license.

PSOC&trade;, formerly known as PSoC&trade;, is a trademark of Infineon Technologies. Any references to PSoC&trade; in this document or others shall be deemed to refer to PSOC&trade;.

---------------------------------------------------------

(c) 2026, Infineon Technologies AG, or an affiliate of Infineon Technologies AG. All rights reserved.
This software, associated documentation and materials ("Software") is owned by Infineon Technologies AG or one of its affiliates ("Infineon") and is protected by and subject to worldwide patent protection, worldwide copyright laws, and international treaty provisions. Therefore, you may use this Software only as provided in the license agreement accompanying the software package from which you obtained this Software. If no license agreement applies, then any use, reproduction, modification, translation, or compilation of this Software is prohibited without the express written permission of Infineon.
<br>
Disclaimer: UNLESS OTHERWISE EXPRESSLY AGREED WITH INFINEON, THIS SOFTWARE IS PROVIDED AS-IS, WITH NO WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, ALL WARRANTIES OF NON-INFRINGEMENT OF THIRD-PARTY RIGHTS AND IMPLIED WARRANTIES SUCH AS WARRANTIES OF FITNESS FOR A SPECIFIC USE/PURPOSE OR MERCHANTABILITY. Infineon reserves the right to make changes to the Software without notice. You are responsible for properly designing, programming, and testing the functionality and safety of your intended application of the Software, as well as complying with any legal requirements related to its use. Infineon does not guarantee that the Software will be free from intrusion, data theft or loss, or other breaches (“Security Breaches”), and Infineon shall have no liability arising out of any Security Breaches. Unless otherwise explicitly approved by Infineon, the Software may not be used in any application where a failure of the Product or any consequences of the use thereof can reasonably be expected to result in personal injury.
