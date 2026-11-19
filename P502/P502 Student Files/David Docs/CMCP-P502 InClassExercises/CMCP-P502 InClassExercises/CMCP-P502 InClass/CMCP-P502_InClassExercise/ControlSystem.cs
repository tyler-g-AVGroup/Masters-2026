using Crestron.SimplSharp;
using Crestron.SimplSharpPro;

namespace CMCP_P502_InClassExercise
{
    public class ControlSystem : CrestronControlSystem
                                // ControlSystem inherits CrestronControlSystem (all programming in CrestonControlSystem, automatically included)
    {

        #region ++++ HARDWARE DEFINITIONS - EXERCISE 1 - STEP 1++++

        // define our hardware here

        //  EXERCISE 1 - STEP 1:  add a definition for a private OurXpanel named myXpanel

        private OurXpanel? myXpanel;


        #region ++++ EXERCISE 1 - STEP 1 example ++++
        /*
        private OurXpanel? myXpanel;
        */
        #endregion

        #endregion

        // -------------------------------------------------------------------------------------------

        #region ++++ CONTROL SYSTEM CONSTRUCTOR ++++


        /// <summary>
        /// Control system constructor this is called when the OS instantiates your Control System
        /// </summary>
        public ControlSystem()
            : base()    // run the CrestronControlSystem constructor first, then run our constructor
        {
            // The first logic that is run as the program is getting loaded
            // This needs to execute quickly or the OS will think somethine went wrong and abort your program.

            // try/catch block to handle if something goes wrong.
            try
            {
                // Tells the OS how many uesr threads to allocate to the program
                Crestron.SimplSharpPro.CrestronThread.Thread.MaxNumberOfUserThreads = 20;

            }
            // if something went wrong while executing the code in the try block, the catch block is called
            // the catch is used to recover from the failure so the program can continue on
            catch (Exception e)
            {
                ErrorLog.Error("Error in Control System Constructor: {0}", e.Message);  // print an error message to the log.
            }
        }

        #endregion

        // --------------------------------------------------------------------------------------------

        #region ++++ INITIALIZE SYSTEM ++++

        /// <summary>
        /// Initialize system is automatically run by the OS once the program is loaded
        /// </summary>
        public override void InitializeSystem()     //notice it's an override method - CrestonControlSystem has a placehoder IntializeSystem that we have to implement
        {
            // try/catch to handle if something goes wrong
            try
            {
                CrestronConsole.PrintLine("Program Initializing!");    //  print a message to console (if there is a console)
                ErrorLog.Notice("This notice brought to you by CMCP-P502: Welcome Students!");  // writes a message to the log

                // ---------------------------------------------------------------------------------

                // EXERCISE 1 - STEP 2: Instantiate myXpanel by creating a new OurXpanel

                myXpanel = new OurXpanel(this); // to create a new xpanel we need to pass the current constrol sytem in as a parameter.  The keyword this is used to do so.


                // EXERCISE 1 - STEP 3:  Test that myXpanel is not null                 
                if (myXpanel != null)
                {
                    // write a notice to the ErrorLog that the xpanel registered
                    ErrorLog.Notice("xpanel Registered.");


                    // EXERCISE 1 - STEP 4: set values for myXpanel.StudentName, myXpanel.YearsAttended, and myXpanel.FirstExperienceCSharp
                    myXpanel.StudentName = "Tyler Gardiner";
                    myXpanel.YearsAttended = 3;
                    myXpanel.FirstExperienceCSharp = false;

                    // EXERCISE 2 - STEP 1: register a method to myXpanel OnlineStatusChanges
                    myXpanel.OnlineStatusChange += MyXpanel_OnlineStatusChange;
                    

                    // EXERCISE 3 - STEP 1: register MyXpanel_Button1Press to myXpanel Button1Press
                    myXpanel.Button1Press += MyXpanel_Button1Press;

                    // EXERCISE 4 - STEP 1: register MyXpanel_Button2Press to myXpanel Button2Press
                    myXpanel.Button2Press += MyXpanel_Button2Press;

                }
                else
                {
                    ErrorLog.Error("XPanel failed to register");    // write an error to the log file
                }

            }
            catch (Exception e)
            {
                ErrorLog.Error("Error in InitializeSystem: {0}", e.Message);
            }
        }

        private void MyXpanel_OnlineStatusChange(object? sender, OurXpanel.OnlineEventArgs e)
        {
            //throw new NotImplementedException();
            if(e.Online)
            {
                if (myXpanel != null) myXpanel.PrintMessage("I'm Online");
            }
        }


        // -----------------------------------------

        #region ++++ InitializeSystem COMPLETED EXAMPLE ++++

        /*
         
        /// <summary>
        /// Initialize system is automatically run by the OS once the program is loaded
        /// </summary>
        public override void InitializeSystem()     //notice it's an override method - CrestonControlSystem has a placehoder IntializeSystem that we have to implement
        {
            // try/catch to handle if something goes wrong
            try
            {
                CrestronConsole.PrintLine("Program Initializing!");    //  print a message to console (if there is a console)
                ErrorLog.Notice("This notice brought to you by CMCP-P502: Welcome Students!");  // writes a message to the log

                // ---------------------------------------------------------------------------------

                // EXERCISE 1 - STEP 2: Instantiate myXpanel by creating a new OurXpanel
                myXpanel = new OurXpanel(this); // to create a new xpanel we need to pass the current constrol sytem in as a parameter.  The keyword this is used to do so.

                // EXERCISE 1 - STEP 3:  Test that myXpanel is not null                 
                if (myXpanel != null)
                {
                    // write a notice to the ErrorLog that the xpanel registered
                    ErrorLog.Notice("Xpanel Registered");   

                    // EXERCISE 1 - STEP 4: set values for myXpanel.StudentName, myXpanel.YearsAttended, and myXpanel.FirstExperienceCSharp
                    myXpanel.StudentName = "New Student";
                    myXpanel.YearsAttended = 1;
                    myXpanel.FirstExperienceCSharp = true;

                    // EXERCISE 2 - STEP 1: register a method to myXpanel OnlineStatusChanges
                    myXpanel.OnlineStatusChange += MyXpanel_OnlineStatusChange;     // register MyXpanel_OnlineStatusChange with myXpanel for online/offline status changes

                    // EXERCISE 3 - STEP 1: register MyXpanel_Button1Press to myXpanel Button1Press
                    myXpanel.Button1Press += MyXpanel_Button1Press;     // register MyXpanel_Button1Press with myXpanel so it will be called when button 1 changes press state

                    // EXERCISE 4 - STEP 1: register MyXpanel_Button2Press to myXpanel Button2Press
                    myXpanel.Button2Press += MyXpanel_Button2Press;
                }
                else
                {
                    ErrorLog.Error("XPanel failed to register");    // write an error to the log file
                }

            }
            catch (Exception e)
            {
                ErrorLog.Error("Error in InitializeSystem: {0}", e.Message);
            }
        }
        */

        #endregion

        //------------------------------------------

        #region ++++ EXERCISE 2 COMPLETED EXAMPLE ++++

        /*
        /// <summary>
        /// Method that gets registered to myXpanel.OnlineStatusChange
        /// </summary>
        /// <param name="sender">a reference to the instance that called the method</param>
        /// <param name="e">the data being provided by the calling instance</param>
        private void MyXpanel_OnlineStatusChange(object? sender, OurXpanel.OnlineEventArgs e)
        {
            // EXERCISE 2 - STEP 2: Test for online vs. offline, if online print messgage to the window

            if (e.Online)   // test to see if this is an online and not an offline event
            {
                if (myXpanel != null) myXpanel.PrintMessage("Hello World!");  // print a message to the message window on the xpanel
            }
        }
        */

        #endregion

        #endregion

        //----------------------------------------------------------------------------------------------

        #region ++++ EXERCISE 3 CODE ++++


        /// <summary>
        /// Method that gets registered to myXpanel.Button1Press
        /// </summary>
        /// <param name="sender">a reference to the instance that called the method</param>
        /// <param name="e">the data being provided by the calling instance</param>
        private void MyXpanel_Button1Press(object? sender, OurXpanel.PressStateEventArgs e)
        {
            // EXERCISE 3 - STEP 2: Add code to toggle the button feedback and print messages to the message window

            // test to make sure myXpanel is not null
            if (myXpanel != null)  
            {
                // test if this is a button press or a button release
                if (e.ButtonPressed)  // press event
                {
                    // test to see what the current state is for myXpanel.Button1fb
                    if (myXpanel.Button1fb) // if button feedback currently 'HIGH/true'
                    {
                        // set myXpanel.Button1fb false
                        myXpanel.Button1fb = false;
                        // print a message to the message window using myXpanel.PrintMessage
                        myXpanel.PrintMessage("Button 1 Cleared");
                    }
                    else // button feedback is currently 'LOW/false'
                    {
                        // set myXpanel.Button1fb true
                        myXpanel.Button1fb = true;  
                        // print a message to be message window using myXpanel.PrintMessage
                        myXpanel.PrintMessage("Button 1 Set");
                    }
                }
            }
        }

        #region EXERCISE 3 COMPLETED EXAMPLE 
        /*
         
        /// <summary>
        /// Method that gets registered to myXpanel.Button1Press
        /// </summary>
        /// <param name="sender">a reference to the instance that called the method</param>
        /// <param name="e">the data being provided by the calling instance</param>
        private void MyXpanel_Button1Press(object? sender, OurXpanel.PressStateEventArgs e)
        {
            // EXERCISE 3 - STEP 2: Add code to toggle the button feedback and print messages to the message window

            // test to make sure myXpanel is not null
            if (myXpanel != null)   
            {
                // test if this is a button press or a button release
                if (e.ButtonPressed)  // press event
                {
                    // test to see what the current state is for myXpanel.Button1fb
                    if (myXpanel.Button1fb)  // if button feedback currently 'HIGH/true'
                    {
                        // set myXpanel.Button1fb false
                        myXpanel.Button1fb = false;
                        // print a message to the message window using myXpanel.PrintMessage
                        myXpanel.PrintMessage("Button 1 Cleared");
                    }
                    else // button feedback is currently 'LOW/false'
                    {
                        // set myXpanel.Button1fb true
                        myXpanel.Button1fb = true;
                        // print a message to be message window using myXpanel.PrintMessage
                        myXpanel.PrintMessage("Button 1 Set");
                    }
                }
            }
        }

         */
        #endregion

        #endregion

        //----------------------------------------------------------------------------------------------

        #region ++++ EXERCISE 4 CODE ++++

        //  EXERCISE 4 - STEP 2: Add code to set feedback true and print a message to the message window
        private void MyXpanel_Button2Press(object? sender, OurXpanel.PressStateEventArgs e)
        {
            // alternate method to handle myXpanel being nullif null, just exit
            //if (myXpanel == null) return;  

            // check to see if the event was a press or a release
            if (e.ButtonPressed)     
            {
                // set myXpanel.Button2fb true
                
                // print a message to the message window using myXpanel.PrintMessage
                


                //  EXERCISE 4 - STEP 5:  Add code to start the timer
                if (false)   // if the button2Timer is null, create a new CTimer
                {
                    
                }
                else    // if the button2Timer already exists, call it again 
                {
                    
                }
            }
        }


        //  EXERCISE 4 STEP 3:  Define a private CTimer called button2Timer         
        


        // EXERCISE 4 STEP 4:  Add a callback method to reset Button2 feedback state 

        /// <summary>
        /// method that gets called when the CTimer expires  
        /// </summary>
        /// <param name="o">object that can be passed from the CTimer</param>
        private void Button2Callback(object? o)
        {
            //if (myXpanel == null)  return;  // check to make sure myPanel is not null

            // set myXpanel.Button2fb false
            

            // print a message to the message window using myXpanel.PrintMessage
            
        }

        //-------------------------------

        #region EXERCISE 4 COMPLETED EXAMPLE 
        /*
        //  EXERCISE 4 - STEP 2: Add code to set feedback true and print a message to the message window
        private void MyXpanel_Button2Press(object? sender, OurXpanel.PressStateEventArgs e)
        {
            // alternate method to handle myXpanel being nullif null, just exit
            //if (myXpanel == null) return;  

            // check to see if the event was a press or a release
            if (e.ButtonPressed)    
            {
                // set myXpanel.Button2fb true
                myXpanel.Button2fb = true;     
                // print a message to the message window using myXpanel.PrintMessage
                myXpanel.PrintMessage("Button 2 Set");   

                //  EXERCISE 4 - STEP 5:  Add code to start the timer
                if (button2Timer == null)   // if the button2Timer is null, create a new CTimer
                {
                    button2Timer = new CTimer(Button2Callback, 5000);
                }
                else     // if the button2Timer already exists, call it again 
                {
                    button2Timer.Reset(5000);
                }
            }
        }

        //  EXERCISE 4 STEP 3:  Define a private CTimer called button2Timer        
        private CTimer? button2Timer;   //  need to use ? to acknowledge that this can be null


        // EXERCISE 4 STEP 4:  Add a callback method to reset Button2 feedback state

        /// <summary>
        /// method that gets called when the CTimer expires  
        /// </summary>
        /// <param name="o">object that can be passed from the CTimer</param>
        private void Button2Callback(object? o)
        {
            if (myXpanel == null)  return;  // check to make sure myPanel is not null
            
            // set myXpanel.Button2fb false
            myXpanel.Button2fb = false;  
            // print a message to the message window using myXpanel.PrintMessage
            myXpanel.PrintMessage("Button 2 Cleared");   
            
        }
        */

        #endregion

        #endregion

    }
}
