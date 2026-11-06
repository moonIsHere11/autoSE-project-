// Spike S5: minimal ProLeap -> JSON CLI, the shape a Python verifier would call via subprocess.
// Usage: java -cp proleap.jar:lib/* ProLeapDump.java <file> <FIXED|TANDEM|VARIABLE> [paragraphToTree]
// Emits one JSON object on stdout: timings, data entries, paragraphs with statements + line numbers.
import io.proleap.cobol.CobolParser;
import io.proleap.cobol.asg.metamodel.*;
import io.proleap.cobol.asg.metamodel.data.DataDivision;
import io.proleap.cobol.asg.metamodel.data.datadescription.*;
import io.proleap.cobol.asg.metamodel.data.file.FileDescriptionEntry;
import io.proleap.cobol.asg.metamodel.procedure.*;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import org.antlr.v4.runtime.ParserRuleContext;
import org.antlr.v4.runtime.tree.Trees;
import java.io.File;
import java.util.*;

public class ProLeapDump {
  static String q(Object o) {
    if (o == null) return "null";
    String s = o.toString().replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n");
    return "\"" + s + "\"";
  }
  static int line(ASGElement e) { ParserRuleContext c = e.getCtx(); return c == null ? -1 : c.getStart().getLine(); }

  static void data(StringBuilder sb, List<DataDescriptionEntry> entries) {
    for (DataDescriptionEntry e : entries) {
      sb.append("  {\"line\":").append(line(e)).append(",\"level\":").append(e.getLevelNumber())
        .append(",\"name\":").append(q(e.getName())).append(",\"kind\":").append(q(e.getDataDescriptionEntryType()));
      if (e instanceof DataDescriptionEntryGroup g) {
        if (g.getPictureClause() != null) sb.append(",\"pic\":").append(q(g.getPictureClause().getPictureString()));
        if (g.getUsageClause() != null) sb.append(",\"usage\":").append(q(g.getUsageClause().getUsageClauseType()));
        if (!g.getOccursClauses().isEmpty()) sb.append(",\"occurs\":").append(q(g.getOccursClauses().get(0).getCtx().getText()));
        if (g.getRedefinesClause() != null) sb.append(",\"redefines\":").append(q(g.getRedefinesClause().getCtx().getText()));
        if (g.getValueClause() != null) sb.append(",\"value\":").append(q(g.getValueClause().getCtx().getText()));
      } else if (e instanceof DataDescriptionEntryCondition c && c.getValueClause() != null) {
        sb.append(",\"value\":").append(q(c.getValueClause().getCtx().getText()));
      }
      sb.append("},\n");
    }
  }

  public static void main(String[] args) throws Exception {
    long t0 = System.nanoTime();
    File f = new File(args[0]);
    Program program = new CobolParserRunnerImpl().analyzeFile(f, CobolSourceFormatEnum.valueOf(args[1]));
    long t1 = System.nanoTime();
    long warm = -1;  // -Drepeat=N: re-parse N times in the same JVM, report the fastest (warm) parse
    for (int i = 0; i < Integer.getInteger("repeat", 0); i++) {
      long a = System.nanoTime();
      new CobolParserRunnerImpl().analyzeFile(f, CobolSourceFormatEnum.valueOf(args[1]));
      long d = (System.nanoTime() - a) / 1_000_000;
      warm = warm < 0 ? d : Math.min(warm, d);
    }
    StringBuilder sb = new StringBuilder("{\"file\":" + q(f) + ",\"analyze_ms\":" + (t1 - t0) / 1_000_000
        + ",\"warm_min_ms\":" + warm + ",\n\"data\":[\n");
    for (CompilationUnit cu : program.getCompilationUnits()) {
      ProgramUnit pu = cu.getProgramUnit();
      DataDivision dd = pu.getDataDivision();
      if (dd.getFileSection() != null)
        for (FileDescriptionEntry fd : dd.getFileSection().getFileDescriptionEntries()) {
          sb.append("  {\"fd\":").append(q(fd.getName())).append(",\"line\":").append(line(fd)).append("},\n");
          data(sb, fd.getDataDescriptionEntries());
        }
      if (dd.getWorkingStorageSection() != null) data(sb, dd.getWorkingStorageSection().getDataDescriptionEntries());
      sb.append("  null],\n\"paragraphs\":[\n");
      for (Paragraph p : pu.getProcedureDivision().getParagraphs()) {
        sb.append("  {\"name\":").append(q(p.getName())).append(",\"line\":").append(line(p)).append(",\"statements\":[");
        for (Statement s : p.getStatements())
          sb.append("\n    {\"type\":").append(q(s.getStatementType())).append(",\"line\":").append(line(s))
            .append(",\"text\":").append(q(s.getCtx().getText())).append("},");
        sb.append("null]},\n");
      }
      sb.append("  null]");
      if (args.length > 2) {
        Paragraph p = pu.getProcedureDivision().getParagraph(args[2]);
        sb.append(",\n\"tree\":").append(q(Trees.toStringTree(p.getCtx(), Arrays.asList(CobolParser.ruleNames))));
      }
    }
    sb.append(",\"total_ms\":").append((System.nanoTime() - t0) / 1_000_000).append("}");
    System.out.println(sb);
  }
}
