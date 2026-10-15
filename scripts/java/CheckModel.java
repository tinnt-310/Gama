package evstation;
import java.util.*;
import org.eclipse.equinox.app.*;
import org.eclipse.emf.common.util.URI;
import org.eclipse.emf.ecore.resource.*;
import org.eclipse.xtext.resource.XtextResourceSet;
import msi.gama.headless.runtime.HeadlessApplication;
import msi.gama.lang.gaml.validation.GamlModelBuilder;
import msi.gaml.compilation.GamlCompilationError;
public class CheckModel implements IApplication {
 public Object start(IApplicationContext context) throws Exception {
  String[] args=(String[])context.getArguments().get("application.args");
  int failures=0;
  for (String path : args) failures += check(path);
  return failures == 0 ? 0 : 1;
 }
 private int check(String path) throws Exception {
  var injector=HeadlessApplication.getInjector();
  var rs=injector.getInstance(XtextResourceSet.class);
  URI uri=URI.createFileURI(new java.io.File(path).getAbsolutePath());
  rs.getResource(uri,true);
  org.eclipse.emf.ecore.util.EcoreUtil.resolveAll(rs);
  int failures=0;
  for(var r:rs.getResources()) for(var e:r.getErrors()) {System.out.println("SYNTAX "+r.getURI()+":"+e.getLine()+":"+e.getColumn()+" "+e.getMessage());failures++;}
  var errors=new ArrayList<GamlCompilationError>();
  var model=new GamlModelBuilder(injector).compile(uri,errors);
  for(var e:errors) { System.out.println("GAML "+e.toString()); }
  if(model==null) {
   var validator=injector.getInstance(org.eclipse.xtext.validation.IResourceValidator.class);
   for(var resource:new ArrayList<Resource>(rs.getResources())) {
    for(var issue:validator.validate(resource,org.eclipse.xtext.validation.CheckMode.ALL,org.eclipse.xtext.util.CancelIndicator.NullImpl)) {
     if(issue.getSeverity()==org.eclipse.xtext.diagnostics.Severity.ERROR)
      System.out.println("IMPORTED_ERROR "+issue.getUriToProblem()+":"+issue.getLineNumber()+" "+issue.getMessage());
    }
   }
   System.out.println("COMPILE_FAIL");return 1;
  }
  System.out.println("COMPILE_PASS"); return failures==0?0:1;
 }
 public void stop() {}
}
