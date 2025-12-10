package pmtech.diig;

import cc.pmtech.pen_activity;

import android.os.Bundle;

public class diig_app_activity extends pen_activity
{
    @Override
	protected void onCreate(Bundle arg0) 
    {
        loadLibs("diig");
        super.onCreate(arg0);
    }
}